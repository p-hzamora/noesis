"""C5b acceptance measurement: the B-bge-production arm against a fresh lexical+graph baseline.

Not a test: never collected by pytest or imported by `src/`. It starts ONLY a testcontainers
Neo4j (pinned image), uses the production C5b adapters, profile, chunker and fusion, and gives
every child process a temporary HOME. The pinned model is prepared into the XDG model cache
(`noesis index model prepare` semantics). Historical L/A1/A2/B reports are not touched.

    env -u VIRTUAL_ENV PYTHONPATH=src:. uv run --extra semantic \
        python -m scripts.retrieval_spike.bge_production --out <dir>

Corpora: (1) the judged 200-record / 70-query fixture, (2) a generated 2,000-record scale
corpus and (3) a long-document variant. A copy of migrated C3 records (F-7) is not available to
this harness; that run stays pending.
"""

# ruff: noqa: T201

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.neo4j_container import pinned_neo4j_image, running_neo4j, wipe_database
from tests.support.noesis_process_support import run_noesis, store_environment
from tests.support.retrieval.retrieval_neo4j_support import (
    build_searcher,
    search_request,
    space_id_of,
)

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.retrieval.application.handlers.commands.rebuild_index_handler import (
    RebuildIndexCommand,
    RebuildIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexCommand,
    SyncIndexHandler,
)
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.domain.policies.token_window_policy import MODEL_MAX_TOKENS
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.http_fetch import (
    https_fetch,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.in_process_text_embedder import (
    InProcessTextEmbedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    ModelCache,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
    OnnxBgeEngine,
    load_engine,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic import (
    Neo4jSemanticCandidateSource,
    Neo4jSemanticProjectionAdapter,
    Neo4jVectorIndexInspector,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic.semantic_graph_contracts import (
    passage_text,
)
from noesis.core.configurations.paths import default_model_cache_dir
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from .corpus import generate_records, load_records, open_env
from .fixtures import FixtureQuery, FixtureRecord, load_queries
from .fixtures import load_records as load_fixture
from .metrics import latency_summary, percentile
from .run_spike import evaluate_filter, evaluate_relevance

SPACE = "default"
OWNER = "bge-production"
WARM_CALLS = 100
RUNS = 3
WARM_UP = 10
PER_CALL_SAMPLES = 20
TAIL_SENTENCE = "The aquarium heater thermostat failed and the tropical fish tank froze overnight."
TAIL_QUERY = "aquarium heater thermostat failure froze the fish tank"


class NeverIdentifier:
    """Ablation: classify every query as ordinary, so identifier queries get plain RRF."""

    def is_identifier(self, text: str) -> bool:
        return False


class Arm:
    """Production C5b adapters over one env, with a preloaded in-process engine."""

    def __init__(self, env: Neo4jKnowledgeEnv, engine: OnnxBgeEngine) -> None:
        self.env = env
        self.engine = engine
        self.embedder = InProcessTextEmbedder(engine.profile, lambda: engine)
        self.cursors = Neo4jIndexCursorStoreAdapter(env.client, env.clock)
        self.writer = Neo4jSemanticProjectionAdapter(env.client, self.embedder, self.cursors)
        self.source = Neo4jSemanticCandidateSource(
            env.client, self.embedder, Neo4jVectorIndexInspector(env.client)
        )
        self.feed = Neo4jRecordChangeFeedAdapter(env.client)
        self.states = Neo4jRecordStateReaderAdapter(env.client)
        self.indexables = Neo4jIndexableRecordReaderAdapter(env.client)

    async def rebuild(self, space_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        result = await RebuildIndexHandler(
            writers=(self.writer,),
            cursors=self.cursors,
            feed=self.feed,
            states=self.states,
            indexables=self.indexables,
        ).handle(RebuildIndexCommand(space_id=space_id, owner=OWNER))
        seconds = time.perf_counter() - started
        indexed = result.projections[0].records_indexed
        return {
            "records_indexed": indexed,
            "seconds": round(seconds, 2),
            "seconds_per_record": round(seconds / max(indexed, 1), 4),
        }

    async def sync(self, space_id: str) -> float:
        started = time.perf_counter()
        await SyncIndexHandler(
            writers=(self.writer,),
            cursors=self.cursors,
            feed=self.feed,
            states=self.states,
            indexables=self.indexables,
        ).handle(SyncIndexCommand(space_id=space_id, owner=OWNER))
        return time.perf_counter() - started

    def searchers(self) -> dict[str, RecordSearcher]:
        ablation = build_searcher(self.env, candidate_sources=(self.source,))
        ablation._identifiers = NeverIdentifier()  # type: ignore[assignment]
        return {
            "L": build_searcher(self.env),
            "B-bge-production": build_searcher(self.env, candidate_sources=(self.source,)),
            "B-bge-ordinary-rrf-ablation": ablation,
        }


async def chunk_stats(arm: Arm, space_id: str) -> dict[str, Any]:
    """Token lengths, >512-token records, chunks and a tail-coverage audit, per record."""
    counts: list[int] = []
    chunks = 0
    uncovered = 0
    after: str | None = None
    while True:
        page = await arm.states.scan_states(space_id, after_id=after, limit=200)
        for state in page:
            if state.record_type not in {"knowledge", "experience"}:
                continue
            record = await arm.indexables.get(
                state.record_id, state.head_revision, space_id=space_id
            )
            tokens = len(arm.engine.tokens(passage_text(record)))
            counts.append(tokens)
            windows = arm.engine._passages.windows(tokens)
            chunks += len(windows)
            uncovered += 0 if not windows or windows[-1].end == tokens else 1
        if len(page) < 200:
            break
        after = page[-1].record_id
    stored = await _single(arm, "MATCH (e:Embedding) RETURN count(e) AS n")
    return {
        "records": len(counts),
        "token_p50": percentile(counts, 0.5),
        "token_p95": percentile(counts, 0.95),
        "token_max": max(counts) if counts else 0,
        "records_over_512_tokens": sum(1 for count in counts if count + 2 > MODEL_MAX_TOKENS),
        "total_embedded_tokens": sum(counts),
        "expected_chunks": chunks,
        "stored_chunk_nodes": stored,
        "records_with_uncovered_tail": uncovered,
    }


async def _single(arm: Arm, cypher: Any) -> int:
    async with await arm.env.client.begin() as transaction:
        rows = await transaction.run(cypher)
    return int(rows[0]["n"])


def child_env(
    home: Path, settings: Neo4jConnectionSettings, cache_root: Path, runtime: Path, mode: str
) -> dict[str, str]:
    return store_environment(
        home,
        SPACE,
        settings,
        NOESIS_RETRIEVAL_SEMANTIC_MODE=mode,
        NOESIS_RETRIEVAL_MODEL_CACHE_DIR=str(cache_root),
        NOESIS_RETRIEVAL_RUNTIME_DIR=str(runtime),
        XDG_CACHE_HOME=str(home / ".cache"),
    )


def timed_cli(
    env: dict[str, str], texts: Sequence[str], *extra: str
) -> tuple[list[float], int, list[str]]:
    seconds: list[float] = []
    failures = 0
    states: list[str] = []
    for text in texts:
        outcome = run_noesis(["search", text, "--all-projects", "--limit", "10", *extra], env)
        seconds.append(outcome.seconds)
        if outcome.code != 0:
            failures += 1
            continue
        index = outcome.result.get("index")
        if isinstance(index, dict) and isinstance(index.get("semantic"), dict):
            states.append(str(index["semantic"].get("state")))
    return seconds, failures, states


def cli_runs(env: dict[str, str], texts: Sequence[str], *extra: str) -> dict[str, Any]:
    """Warm-up, then `RUNS` runs of `WARM_CALLS` fresh CLI processes each."""
    timed_cli(env, texts[:WARM_UP], *extra)
    runs: list[dict[str, Any]] = []
    every: list[float] = []
    failures = 0
    states: list[str] = []
    for _ in range(RUNS):
        seconds, failed, found = timed_cli(env, texts[:WARM_CALLS], *extra)
        runs.append(latency_summary(seconds))
        every += seconds
        failures += failed
        states += found
    return {
        "runs": runs,
        "all": latency_summary(every),
        "failures": failures,
        "semantic_states": sorted(set(states)),
        "quantile": "nearest-rank",
    }


def start_embedder(env: dict[str, str]) -> tuple[subprocess.Popen[str], float]:
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-m", "noesis", "index", "embedder", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    runtime = Path(env["NOESIS_RETRIEVAL_RUNTIME_DIR"]) / "noesis"
    while time.monotonic() - started < 120:
        if runtime.exists() and any(runtime.glob("*.sock")):
            return process, time.monotonic() - started
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read() if process.stderr else "embedder died")
        time.sleep(0.05)
    raise RuntimeError("embedder did not start")


def peak_rss_kb(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


async def run_fixture(
    settings: Neo4jConnectionSettings, engine: OnnxBgeEngine, cache_root: Path
) -> dict[str, Any]:
    records = load_fixture()
    queries = load_queries()
    env = await open_env(settings)
    try:
        space_id = await space_id_of(env)
        load = await load_records(env, space_id, records)
        to_key = {record_id: key for key, record_id in load.ids.items()}
        arm = Arm(env, engine)
        print("fixture: rebuild", flush=True)
        rebuild = await arm.rebuild(space_id)
        stats = await chunk_stats(arm, space_id)
        relevance: dict[str, Any] = {}
        filtered: dict[str, Any] = {}
        for name, searcher in arm.searchers().items():
            print(f"fixture: relevance {name}", flush=True)
            found = await evaluate_relevance(searcher, space_id, queries, to_key, passes=3)
            found.pop("per_query")
            relevance[name] = found
            filtered[name] = await evaluate_filter(searcher, space_id, queries, records, to_key)
        print("fixture: lag", flush=True)
        lag = await commit_to_cursor_lag(env, arm, space_id, records)
        print("fixture: cli", flush=True)
        cli = cli_latency(settings, queries, cache_root)
        return {
            "corpus": {"records": len(records), "queries": len(queries)},
            "rebuild": rebuild,
            "chunks": stats,
            "relevance": relevance,
            "project_filter": filtered,
            "lag": lag,
            "cli": cli,
        }
    finally:
        await env.client.close()


async def commit_to_cursor_lag(
    env: Neo4jKnowledgeEnv, arm: Arm, space_id: str, records: Sequence[FixtureRecord]
) -> dict[str, Any]:
    """Capture one record, then an explicit in-process sync: commit to cursor, 10 samples."""
    from .corpus import capture

    seconds: list[float] = []
    for index in range(10):
        template = records[index]
        record = FixtureRecord(
            key=f"lag-{index}",
            cluster="lag",
            kind="knowledge",
            subtype="decision",
            status=None,
            project=None,
            lang="en",
            title=f"Lag probe {index}",
            body=template.body,
            source_locator=f"{index + 9000:040x}",
        )
        started = time.perf_counter()
        await capture(env, record)
        await arm.sync(space_id)
        seconds.append(time.perf_counter() - started)
    return {
        "explicit_sync": latency_summary(seconds),
        "note": "capture commit plus an in-process `index sync`; the detached post-write trigger "
        "adds a process start (measured as CLI process floor) and was not timed separately",
    }


def cli_latency(
    settings: Neo4jConnectionSettings, queries: Sequence[FixtureQuery], cache_root: Path
) -> dict[str, Any]:
    texts = [query.text for query in queries]
    texts = (texts * (WARM_CALLS // len(texts) + 1))[: max(WARM_CALLS, WARM_UP)]
    home = Path(tempfile.mkdtemp(prefix="bge-home-"))
    runtime = Path(tempfile.mkdtemp(prefix="nbge-"))
    found: dict[str, Any] = {}
    try:
        off = child_env(home, settings, cache_root, runtime, "off")
        floor = [run_noesis(["--help"], off, json_output=False).seconds for _ in range(5)]
        found["process_floor_help"] = latency_summary(floor)
        print("cli: L (mode off)", flush=True)
        found["L"] = cli_runs(off, texts)
        resident = child_env(home, settings, cache_root, runtime, "resident")
        process, startup = start_embedder(resident)
        try:
            found["embedder_cold_start_seconds"] = round(startup, 2)
            print("cli: resident", flush=True)
            found["resident_semantic"] = cli_runs(resident, texts)
            print("cli: resident during rebuild", flush=True)
            found["resident_during_rebuild"] = during_rebuild(resident, texts)
            found["embedder_peak_rss_kb"] = peak_rss_kb(process.pid)
        finally:
            stop(process)
        per_call = child_env(home, settings, cache_root, runtime, "per-call")
        print("cli: per-call", flush=True)
        seconds, failures, states = timed_cli(per_call, texts[:PER_CALL_SAMPLES], "--semantic")
        found["per_call_opt_in"] = {
            **latency_summary(seconds),
            "failures": failures,
            "semantic_states": sorted(set(states)),
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(runtime, ignore_errors=True)
    return found


def during_rebuild(env: dict[str, str], texts: Sequence[str]) -> dict[str, Any]:
    """Search while a resident `index rebuild` competes for the embedder; failures count."""
    rebuild = subprocess.Popen(
        [sys.executable, "-m", "noesis", "index", "rebuild", "--yes", "--json"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    seconds, failures, states = timed_cli(env, texts[:30])
    out, _ = rebuild.communicate(timeout=1200)
    return {
        **latency_summary(seconds),
        "failures": failures,
        "semantic_states": sorted(set(states)),
        "rebuild_exit": rebuild.returncode,
        "rebuild_result": json.loads(out).get("result") if out.strip() else None,
        "note": "states are `unavailable` while the space is rebuilding (Q-207); search continues",
    }


async def run_scale(
    settings: Neo4jConnectionSettings, engine: OnnxBgeEngine, *, long_documents: bool
) -> dict[str, Any]:
    records = generate_records(2_000 if not long_documents else 300)
    if long_documents:
        records = [
            dataclasses.replace(
                record,
                body=" ".join([record.body] * 60) + (" " + TAIL_SENTENCE if index == 7 else ""),
            )
            for index, record in enumerate(records)
        ]
    env = await open_env(settings)
    try:
        space_id = await space_id_of(env)
        load = await load_records(env, space_id, records, status_share=0.0)
        arm = Arm(env, engine)
        rebuild = await arm.rebuild(space_id)
        stats = await chunk_stats(arm, space_id)
        found: dict[str, Any] = {"records": len(records), "rebuild": rebuild, "chunks": stats}
        if long_documents:
            hits = await arm.source.find(TAIL_QUERY, space_id=space_id, limit=10)
            needle = load.ids[records[7].key]
            found["tail_only_phrase_rank"] = next(
                (rank for rank, key in enumerate(hits.hits, start=1) if key.record_id == needle),
                None,
            )
        searcher = arm.searchers()["B-bge-production"]
        latencies: list[float] = []
        for text in ["deployment pipeline retries", "cache invalidation bug", "svc-0042"] * 10:
            started = time.perf_counter()
            await searcher.search(search_request(text, space_id, all_projects=True))
            latencies.append(time.perf_counter() - started)
        found["in_process_search"] = latency_summary(latencies)
        found["over_fetch_attempts_last"] = arm.source.last_attempts
        return found
    finally:
        await env.client.close()


def hardware() -> dict[str, Any]:
    cpu = ""
    with contextlib.suppress(OSError, StopIteration):
        cpu = next(
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        )
    memory = ""
    with contextlib.suppress(OSError):
        memory = Path("/proc/meminfo").read_text().splitlines()[0]
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu,
        "cpus": os.cpu_count(),
        "memory": memory,
        "neo4j_image": pinned_neo4j_image(),
    }


async def relevance_only(out: Path, engine: OnnxBgeEngine) -> None:
    """Rerun only the fixture relevance and filter evaluation (after a fusion tuning)."""
    records = load_fixture()
    queries = load_queries()
    with running_neo4j() as settings:
        env = await open_env(settings)
        try:
            space_id = await space_id_of(env)
            load = await load_records(env, space_id, records)
            to_key = {record_id: key for key, record_id in load.ids.items()}
            arm = Arm(env, engine)
            report: dict[str, Any] = {"rebuild": await arm.rebuild(space_id), "relevance": {}}
            report["project_filter"] = {}
            for name, searcher in arm.searchers().items():
                found = await evaluate_relevance(searcher, space_id, queries, to_key, passes=1)
                report["relevance"][name] = {
                    "per_slice": found["per_slice"],
                    "identifier_rows": [
                        {key: row[key] for key in ("id", "ranked", "ndcg", "sources")}
                        for row in found["per_query"]
                        if row["slice"] == "identifier"
                    ],
                }
                report["project_filter"][name] = await evaluate_filter(
                    searcher, space_id, queries, records, to_key
                )
        finally:
            await env.client.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / "b-bge-production-relevance-rerun.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps({n: r["per_slice"] for n, r in report["relevance"].items()}, indent=1))


async def main_async(out: Path, *, only_relevance: bool = False) -> None:
    cache_root = Path(os.environ.get("NOESIS_RETRIEVAL_MODEL_CACHE_DIR", default_model_cache_dir()))
    cache = ModelCache(cache_root)
    started = time.perf_counter()
    prepared = cache.prepare(https_fetch)
    prepare_seconds = time.perf_counter() - started
    started = time.perf_counter()
    engine = load_engine(cache)
    load_seconds = time.perf_counter() - started
    if only_relevance:
        await relevance_only(out, engine)
        return
    if os.environ.get("BGE_ONLY_LONG"):
        with running_neo4j() as settings:
            long_run = await run_scale(settings, engine, long_documents=True)
        out.mkdir(parents=True, exist_ok=True)
        (out / "b-bge-production-long-rerun.json").write_text(json.dumps(long_run, indent=2))
        print(json.dumps(long_run, indent=1))
        return
    report: dict[str, Any] = {
        "arm": "B-bge-production",
        "profile": engine.profile.as_json(),
        "profile_hash": engine.profile.fingerprint(),
        "artifact": prepared.model_dump(mode="json"),
        "prepare_seconds": round(prepare_seconds, 2),
        "model_load_seconds_in_process": round(load_seconds, 2),
        "hardware": hardware(),
        "packages": _packages(),
        "f7_migrated_copy": "pending: no exported copy of migrated C3 records was supplied",
    }
    with running_neo4j() as settings:
        report["fixture"] = await run_fixture(settings, engine, cache_root)
        wipe_database(settings)
        print("scale: 2,000 records", flush=True)
        report["scale_2000"] = await run_scale(settings, engine, long_documents=False)
        wipe_database(settings)
        print("scale: long documents", flush=True)
        report["long_documents"] = await run_scale(settings, engine, long_documents=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "b-bge-production.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary(report), indent=2))


def _packages() -> dict[str, str]:
    from importlib.metadata import version

    return {name: version(name) for name in ("numpy", "onnxruntime", "tokenizers", "neo4j")}


def summary(report: dict[str, Any]) -> dict[str, Any]:
    fixture = report["fixture"]
    rel = fixture["relevance"]

    def slice_of(arm: str, name: str) -> float:
        return float(rel[arm]["per_slice"][name]["ndcg@10"])

    return {
        "english_ndcg": {arm: slice_of(arm, "en-en") for arm in rel},
        "identifier_ndcg": {arm: slice_of(arm, "identifier") for arm in rel},
        "filtered_over_unfiltered": {
            arm: fixture["project_filter"][arm]["filtered_over_unfiltered"] for arm in rel
        },
        "cli_p95_ms": {
            "L": fixture["cli"]["L"]["all"]["p95_ms"],
            "resident": fixture["cli"]["resident_semantic"]["all"]["p95_ms"],
            "per_call": fixture["cli"]["per_call_opt_in"]["p95_ms"],
        },
        "lag_p95_ms": fixture["lag"]["explicit_sync"]["p95_ms"],
        "rebuild_2000_seconds": report["scale_2000"]["rebuild"]["seconds"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only-relevance", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.out, only_relevance=args.only_relevance))


if __name__ == "__main__":
    main()
