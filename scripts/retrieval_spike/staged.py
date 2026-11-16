"""Staged driver for arms A1, A2 and B: every stage finishes quickly and persists JSON to disk.

Not a test and never imported by `src/`. Run from the repository root:

    env -u VIRTUAL_ENV PYTHONPATH=src:. uv run python -m scripts.retrieval_spike.staged \\
        --state DIR STAGE ARM [--phase cold|warm --offset N --count N --samples N]

`DIR/container.json` names a long-lived pinned Neo4j container (`docker run -d`, label
`c5a-spike`); each stage writes `DIR/<ARM>/<stage>.json` and the next stage resumes from disk.
Stages: fx-load fx-rebuild fx-relevance fx-spot fx-cli fx-stale fx-lag fx-embed sc-load
sc-rebuild (detached, polled) sc-relevance sc-cli, then `report`.
"""

# ruff: noqa: T201, S101, S603

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from tests.support.neo4j_container import wipe_database

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from . import run_spike as rs
from . import semantic_measure as sm
from .arms import ARMS, VectraArm
from .corpus import LoadResult, generate_records, load_records, open_env
from .fixtures import load_queries
from .fixtures import load_records as load_fixture
from .metrics import latency_summary
from .vectra_arm import (
    VectraHelperCandidateSource,
    VectraHelperProcess,
    run_vectra,
)

CLI_SAMPLE = 20
SCALE_RECORDS = 2000
STALE_KEYS = rs.STALE_KEYS


def settings_of(state: Path) -> Neo4jConnectionSettings:
    """Connection to the long-lived container."""
    data = json.loads((state / "container.json").read_text())
    return Neo4jConnectionSettings(
        uri=data["uri"],
        user=data["user"],
        password=SecretStr(data["password"]),
        connect_timeout_seconds=10.0,
    )


def sample_queries() -> list[Any]:
    """The 20 judged queries every CLI latency sample uses, spread over the slices."""
    judged = [query for query in load_queries() if query.slice != "none"]
    return judged[:: len(judged) // CLI_SAMPLE][:CLI_SAMPLE]


def save(path: Path, data: Any) -> None:
    """Write a stage's JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str))
    print(f"wrote {path}", flush=True)


def load_json(path: Path) -> Any:
    """Read a stage's JSON."""
    return json.loads(path.read_text())


class Stage:
    """Everything one stage needs: arm, directories, the container and the arm's registered parts."""

    def __init__(self, state: Path, arm_name: str) -> None:
        self.state = state
        self.arm_name = arm_name
        self.dir = state / arm_name
        self.workdir = self.dir / "work"
        self.settings = settings_of(state)
        self.arm = ARMS[arm_name]
        self.ctx = sm.ArmContext(self.arm, self.workdir)
        os.environ.update(self.ctx.env_extra())
        sm.point_hf_cache()
        self.helper: VectraHelperProcess | None = None

    def path(self, name: str) -> Path:
        """Stage output path."""
        return self.dir / f"{name}.json"

    def load_result(self, prefix: str) -> tuple[LoadResult, str]:
        """The ids of the corpus loaded by `<prefix>-load`, and the space id."""
        data = load_json(self.path(f"{prefix}-load"))
        result = LoadResult(ids=data["ids"])
        return result, data["space_id"]

    async def registered(self, env: Any) -> Any:
        """The arm's projection; for A the candidate source is the resident Vectra helper."""
        registered = self.arm.registered(env.client, None)  # type: ignore[arg-type]
        if isinstance(self.arm, VectraArm):
            settings = self.arm.settings()
            self.helper = VectraHelperProcess(settings)
            await self.helper.start()
            registered = type(registered)(
                writers=registered.writers,
                candidate_sources=(VectraHelperCandidateSource(settings, self.helper),),
                cursors=registered.cursors,
            )
        return registered

    async def close(self) -> None:
        """Stop helper processes."""
        if self.helper is not None:
            await self.helper.close()
        kit = getattr(self.arm, "kit", None)
        if kit is not None:
            await kit.embedder.close()


async def load(stage: Stage, prefix: str, records: list[Any], status_share: float) -> None:
    """Wipe the container and the arm's working directory, then capture `records`."""
    shutil.rmtree(stage.workdir, ignore_errors=True)
    stage.workdir.mkdir(parents=True)
    wipe_database(stage.settings)
    env = await open_env(stage.settings)
    try:
        space_id = await rs.space_id_of(env)
        result = await load_records(env, space_id, records, status_share=status_share)
        extra: dict[str, Any] = {}
        if prefix == "sc":
            await sm.checkpoint(env)
            extra["neo4j_disk_before_index"] = sm.neo4j_disk_kb(stage.settings)
        save(
            stage.path(f"{prefix}-load"),
            {
                "ids": result.ids,
                "space_id": space_id,
                "load": rs._load_summary(result),
                "corpus_records": len(records),
                **extra,
            },
        )
    finally:
        await env.client.close()


async def fx_rebuild(stage: Stage) -> None:
    """`index rebuild --yes` through the launcher on the fixture corpus."""
    outcome = sm.index_rebuild(stage.ctx, stage.settings)
    env = await open_env(stage.settings)
    try:
        await sm.checkpoint(env)
    finally:
        await env.client.close()
    save(
        stage.path("fx-rebuild"),
        {
            "rebuild": outcome,
            "arm_store": sm.arm_store_kb(stage.ctx),
            "neo4j_disk": sm.neo4j_disk_kb(stage.settings),
        },
    )


async def relevance(stage: Stage, prefix: str, passes: int) -> None:
    """Fused-output metrics with the arm's candidate source (helper-backed for A)."""
    queries = load_queries()
    records = load_fixture()
    ids, space_id = stage.load_result(prefix)
    to_key = {record_id: key for key, record_id in ids.ids.items()}
    env = await open_env(stage.settings)
    try:
        registered = await stage.registered(env)
        searcher = sm.build_arm_searcher(env, registered)
        result = await rs.evaluate_relevance(searcher, space_id, queries, to_key, passes=passes)
        out: dict[str, Any] = {"relevance": result}
        if prefix == "fx":
            out["project_filter"] = await rs.evaluate_filter(
                searcher, space_id, queries, records, to_key
            )
        if stage.helper is not None:
            out["helper_ready"] = stage.helper.ready
        kit = getattr(stage.arm, "kit", None)
        if kit is not None:
            out["embedder_ready"] = kit.embedder.ready
            out["query_embed_ms_in_search"] = latency_summary(
                [ms / 1000 for ms in kit.embedder.encode_ms]
            )
            out["neo4j_vector_query_seconds"] = latency_summary(kit.source.query_seconds)
        if prefix == "sc":
            out["relevance"].pop("per_query")
            await sm.checkpoint(env)
            out["neo4j_disk_after_index"] = sm.neo4j_disk_kb(stage.settings)
            out["arm_store"] = sm.arm_store_kb(stage.ctx)
            out["index_commands"] = sm.index_commands(stage.ctx, stage.settings)
        save(stage.path(f"{prefix}-relevance"), out)
    finally:
        await stage.close()
        await env.client.close()


async def fx_spot(stage: Stage) -> None:
    """Helper top-10 paths against the `vectra search` CLI on 6 queries (arms A only)."""
    assert isinstance(stage.arm, VectraArm)
    settings = stage.arm.settings()
    _ids, space_id = stage.load_result("fx")
    helper = VectraHelperProcess(settings)
    await helper.start()
    rows = []
    judged = [query for query in load_queries() if query.slice != "none"]
    try:
        for query in judged[:: len(judged) // 6][:6]:
            collection = settings.collection(space_id)
            reply = await helper.search(collection, query.text, 10)
            started = time.perf_counter()
            cli = await run_vectra(settings, "search", collection, query.text, "--top-k", "10")
            seconds = time.perf_counter() - started
            cli_paths = [hit["path"] for hit in cli["hits"]]  # type: ignore[index]
            rows.append(
                {
                    "query": query.id,
                    "equal": reply["paths"] == cli_paths,
                    "n": len(cli_paths),
                    "cli_seconds": round(seconds, 2),
                }
            )
    finally:
        await helper.close()
    save(stage.path("fx-spot"), {"rows": rows, "all_equal": all(row["equal"] for row in rows)})


def fx_cli(stage: Stage, corpus: str, phase: str, offset: int, count: int) -> None:
    """A chunk of the 20-query CLI latency sample through the launcher (fresh process per call)."""
    queries = sample_queries()[offset : offset + count]
    key = f"{corpus}-cli-{phase}-{offset}"
    rows = []
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = stage.ctx.cli_env(Path(home_name), stage.settings)
        floor: list[float] = []
        if offset == 0 and phase == "cold":
            floor = [stage.ctx.run(["--help"], env, json_output=False).seconds for _ in range(3)]
        for query in queries:
            outcome = stage.ctx.run(rs._cli_args(query), env)
            row: dict[str, Any] = {
                "id": query.id,
                "seconds": round(outcome.seconds, 3),
                "exit": outcome.code,
            }
            if outcome.code == 0:
                result = outcome.result
                row["ids"] = [hit["id"] for hit in result["hits"]]  # type: ignore[index]
                row["index"] = result["index"]
            rows.append(row)
    save(stage.path(key), {"rows": rows, "floor_help_seconds": floor})


async def fx_stale(stage: Stage) -> None:
    """Revise five records, search before and after an explicit `index sync`."""
    records = load_fixture()
    by_key = {record.key: record for record in records}
    ids, space_id = stage.load_result("fx")
    env = await open_env(stage.settings)
    try:
        registered = await stage.registered(env)
        searcher = sm.build_arm_searcher(env, registered)
        stale = await rs.stale_after_revise(
            env, searcher, stage.settings, space_id, ids, by_key, STALE_KEYS, stage.ctx
        )
        after = await sm.stale_after_sync(
            registered,
            searcher,
            stage.ctx,
            stage.settings,
            space_id,
            list(STALE_KEYS),
            ids.ids,
            {key: by_key[key].title or "" for key in STALE_KEYS},
        )
        save(stage.path("fx-stale"), {"stale_after_revise": stale, "stale_after_sync": after})
    finally:
        await stage.close()
        await env.client.close()


async def fx_lag(stage: Stage, samples: int) -> None:
    """Indexing lag: capture commit to `index sync` exit with the cursor at head."""
    _ids, space_id = stage.load_result("fx")
    env = await open_env(stage.settings)
    try:
        registered = await stage.registered(env)
        lag = await sm.measure_lag(env, stage.ctx, stage.settings, registered, space_id, samples)
        save(stage.path("fx-lag"), lag)
    finally:
        await stage.close()
        await env.client.close()


async def fx_embed(stage: Stage) -> None:
    """Embedding service evidence: start-up cost and resident per-query latency."""
    records = load_fixture()
    queries = [query for query in load_queries() if query.slice != "none"]
    model = str(stage.arm.spec.model_id)
    save(
        stage.path("fx-embed"),
        {
            "service": await sm.embedding_service(model, sm.record_texts(records), queries),
            "model_cache_kb": sm.model_cache_kb(model),
            "vectra_env_kb": sm.vectra_env_kb(),
        },
    )


def sc_rebuild_run(stage: Stage) -> None:
    """The detached target: `index rebuild --yes` on the scale corpus with a long timeout."""
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = stage.ctx.cli_env(Path(home_name), stage.settings)
        env_file = Path(home_name) / "empty.env"
        env_file.touch()
        started = time.monotonic()
        process = subprocess.run(
            [
                sys.executable,
                str(sm.LAUNCHER),
                "--env-file",
                str(env_file),
                "index",
                "rebuild",
                "--yes",
                "--json",
            ],
            env=env,
            cwd=home_name,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        seconds = time.monotonic() - started
    try:
        result = json.loads(process.stdout)
    except ValueError:
        result = {"stdout": process.stdout[:600], "stderr": process.stderr[:600]}
    save(
        stage.path("sc-rebuild"),
        {"exit": process.returncode, "wall_seconds": round(seconds, 2), "result": result},
    )


def main() -> None:
    """Dispatch one stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("stage")
    parser.add_argument("arm")
    parser.add_argument("--phase", default="cold")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()
    stage = Stage(args.state, args.arm)
    began = time.perf_counter()
    name = args.stage
    if name == "fx-load":
        asyncio.run(load(stage, "fx", load_fixture(), 1.0))
    elif name == "fx-rebuild":
        asyncio.run(fx_rebuild(stage))
    elif name == "fx-relevance":
        asyncio.run(relevance(stage, "fx", 3))
    elif name == "fx-spot":
        asyncio.run(fx_spot(stage))
    elif name in ("fx-cli", "sc-cli"):
        fx_cli(stage, name[:2], args.phase, args.offset, args.count)
    elif name == "fx-stale":
        asyncio.run(fx_stale(stage))
    elif name == "fx-lag":
        asyncio.run(fx_lag(stage, args.samples))
    elif name == "fx-embed":
        asyncio.run(fx_embed(stage))
    elif name == "sc-load":
        fixtures = load_fixture()
        generated = generate_records(SCALE_RECORDS - len(fixtures))
        asyncio.run(load(stage, "sc", [*fixtures, *generated], 0.5))
    elif name == "sc-rebuild":
        sc_rebuild_run(stage)
    elif name == "sc-relevance":
        asyncio.run(relevance(stage, "sc", 1))
    else:
        raise SystemExit(f"unknown stage {name}")
    print(f"stage {name} {args.arm} took {time.perf_counter() - began:.1f}s", flush=True)


if __name__ == "__main__":
    main()
