"""Measurements that only make sense for arms with a projection (A1, A2, B).

Everything here drives the same machinery C5b will use: the CLI through the launcher (which swaps
`registered_projections`), `index rebuild`, `index sync`, `index status`, and the in-process
`RecordSearcher` with the arm's candidate source and cursor store.
"""

# ruff: noqa: T201, S101, S603, S607

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import ProcessResult, finish, store_environment
from tests.support.retrieval.retrieval_neo4j_support import search_request

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_text_search_adapter import (
    Neo4jRecordTextSearchAdapter,
)
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import RegisteredProjections
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from .arms import SpikeArm
from .corpus import capture, generate_records
from .fixtures import FixtureQuery, FixtureRecord
from .metrics import latency_summary
from .neo4j_vector_arm import EmbedderProcess
from .vectra_arm import HF_HOME, document_text

LAUNCHER: Final[Path] = Path(__file__).resolve().parent / "launcher.py"
SPACE: Final[str] = "default"


@dataclass(slots=True)
class ArmContext:
    """A running arm: which arm, and the working directory every process shares."""

    arm: SpikeArm
    workdir: Path

    def env_extra(self) -> dict[str, str]:
        """Variables the launcher and the arm need in every child process."""
        return {"SPIKE_ARM": self.arm.spec.name, "SPIKE_WORKDIR": str(self.workdir)}

    def run(
        self, args: list[str], env: dict[str, str], *, json_output: bool = True
    ) -> ProcessResult:
        """One `noesis` process with the arm's projection registered (through the launcher)."""
        home = Path(env["HOME"])
        env_file = home / "empty.env"
        env_file.touch()
        tail = ["--json"] if json_output else []
        started = time.monotonic()
        process = subprocess.Popen(
            [sys.executable, str(LAUNCHER), "--env-file", str(env_file), *args, *tail],
            env=env,
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return finish(process, started)

    def cli_env(self, home: Path, settings: Neo4jConnectionSettings) -> dict[str, str]:
        """Child environment: isolated HOME, the container's Neo4j and the arm variables."""
        return store_environment(home, SPACE, settings, **self.env_extra())


def build_arm_searcher(env: Neo4jKnowledgeEnv, registered: RegisteredProjections) -> RecordSearcher:
    """`RecordSearcher` like the CLI builds it, with the arm's sources and cursor store."""
    client = env.client
    return RecordSearcher(
        Neo4jRecordTextSearchAdapter(client),
        Neo4jRecordStateReaderAdapter(client),
        Neo4jRecordNeighbourReaderAdapter(client),
        Neo4jIndexableRecordReaderAdapter(client),
        registered.candidate_sources,
        registered.cursors or Neo4jIndexCursorStoreAdapter(client, env.clock),
        Neo4jRecordChangeFeedAdapter(client),
        projection_kinds=tuple(writer.kind for writer in registered.writers),
    )


def _outcome(args: list[str], outcome: ProcessResult) -> dict[str, Any]:
    body: Any = None
    try:
        envelope = outcome.envelope
        body = envelope.get("result") if outcome.code == 0 else envelope
    except ValueError, AssertionError:
        body = {"stdout": outcome.stdout[:500], "stderr": outcome.stderr[:500]}
    return {
        "command": " ".join(args),
        "exit": outcome.code,
        "wall_seconds": round(outcome.seconds, 3),
        "result": body,
    }


def index_rebuild(ctx: ArmContext, settings: Neo4jConnectionSettings) -> dict[str, Any]:
    """`noesis index rebuild --yes` through the launcher (a fresh process, so a cold embedder)."""
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = ctx.cli_env(Path(home_name), settings)
        return _outcome(["index", "rebuild", "--yes"], ctx.run(["index", "rebuild", "--yes"], env))


def index_commands(ctx: ArmContext, settings: Neo4jConnectionSettings) -> dict[str, Any]:
    """`index sync` and `index status --verify` after a rebuild: nothing pending, no divergence."""
    out: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = ctx.cli_env(Path(home_name), settings)
        for name, args in (
            ("sync", ["index", "sync"]),
            ("status_verify", ["index", "status", "--verify"]),
        ):
            out[name] = _outcome(args, ctx.run(args, env))
    return out


def cli_search_sample(
    ctx: ArmContext, settings: Neo4jConnectionSettings, text: str
) -> dict[str, Any]:
    """One CLI search's `index` block (semantic.state, pending_changes, stale_hits) and sources."""
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = ctx.cli_env(Path(home_name), settings)
        args = ["search", text, "--all-projects", "--limit", "10"]
        outcome = ctx.run(args, env)
        result = outcome.result
        hits = result["hits"]
        assert isinstance(hits, list)
        return {
            "index": result["index"],
            "sources_seen": sorted({kind for hit in hits for kind in hit["sources"]}),
            "hits": len(hits),
        }


async def measure_lag(
    env: Neo4jKnowledgeEnv,
    ctx: ArmContext,
    settings: Neo4jConnectionSettings,
    registered: RegisteredProjections,
    space_id: str,
    samples: int,
) -> dict[str, Any]:
    """Capture one record (commit), then `index sync` in a fresh process until the cursor passes.

    Lag is measured from the instant the capture handler returned (its transaction committed)
    to the instant the `index sync` process exited with the cursor at the head. A no-op
    `index sync` gives the process floor for the same command.
    """
    records: list[FixtureRecord] = generate_records(samples, seed=99)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        cli_env = ctx.cli_env(Path(home_name), settings)
        idle = [ctx.run(["index", "sync"], cli_env).seconds for _ in range(3)]
        source = registered.candidate_sources[0]
        for record in records:
            env.clock.current += timedelta(seconds=1)
            record_id = await capture(env, record)
            committed = time.perf_counter()
            outcome = ctx.run(["index", "sync"], cli_env)
            lag = time.perf_counter() - committed
            result = outcome.result
            projection = result["projections"][0]  # type: ignore[index]
            found = await source.find(record.title or record.body, space_id=space_id, limit=10)
            rows.append(
                {
                    "key": record.key,
                    "lag_seconds": round(lag, 3),
                    "applied": projection["applied"],
                    "cursor": projection["cursor"],
                    "head_sequence": result["head_sequence"],
                    "cursor_at_head": projection["cursor"] == result["head_sequence"],
                    "found_by_semantic_source_after_sync": any(
                        key.record_id == record_id for key in found.hits
                    ),
                }
            )
    return {
        "samples": rows,
        "lag_seconds": latency_summary([row["lag_seconds"] for row in rows]),
        "all_cursors_at_head": all(row["cursor_at_head"] for row in rows),
        "noop_index_sync_seconds": latency_summary(idle),
        "definition": "capture handler returned (committed) to `index sync` process exit with "
        "cursor at head; includes process start, import, model load and the store write",
    }


async def stale_after_sync(
    registered: RegisteredProjections,
    searcher: RecordSearcher,
    ctx: ArmContext,
    settings: Neo4jConnectionSettings,
    space_id: str,
    keys: list[str],
    ids: dict[str, str],
    old_titles: dict[str, str],
) -> dict[str, Any]:
    """After the revises of `stale_after_revise`: sync, then the old and new text again."""
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = ctx.cli_env(Path(home_name), settings)
        sync = _outcome(["index", "sync"], ctx.run(["index", "sync"], env))
    rows: list[dict[str, Any]] = []
    for number, key in enumerate(keys, start=1):
        record_id = ids[key]
        new = await searcher.search(
            search_request(
                f"quokkafresh{number} replacement heading",
                space_id,
                all_projects=True,
                statuses=("proposed",),
            )
        )
        old = await searcher.search(
            search_request(old_titles[key], space_id, all_projects=True, statuses=("proposed",))
        )
        new_hit = next((hit for hit in new.hits if hit.record_id == record_id), None)
        old_hit = next((hit for hit in old.hits if hit.record_id == record_id), None)
        rows.append(
            {
                "key": key,
                "new_text_revision": new_hit.revision if new_hit else None,
                "new_text_sources": [kind.value for kind in new_hit.sources] if new_hit else [],
                "old_title_revision": old_hit.revision if old_hit else None,
                "stale_hits": new.stale_hits + old.stale_hits,
                "state": old.semantic_state.value,
            }
        )
    return {
        "sync": sync,
        "rows": rows,
        "stale_hits_total_after_sync": sum(row["stale_hits"] for row in rows),
        "served_old_revision": sum(1 for row in rows if row["old_title_revision"] not in (None, 2)),
        "new_text_found_at_head": sum(1 for row in rows if row["new_text_revision"] == 2),
        "new_text_found_by_semantic": sum(
            1 for row in rows if "semantic" in row["new_text_sources"]
        ),
    }


async def embedding_service(
    model_id: str, texts: list[str], queries: list[FixtureQuery], starts: int = 3
) -> dict[str, Any]:
    """Embedding cost with a resident model, and model start-up cost (the background-service case).

    Start-up is a fresh helper process each time (interpreter, torch import, model load). The
    first start of the run may also pay disk reads; later starts hit the page cache, so the
    cold figure is "first in this run", not a dropped-cache measurement.
    """
    start_ups: list[dict[str, Any]] = []
    resident: EmbedderProcess | None = None
    for _ in range(starts):
        embedder = EmbedderProcess(model_id)
        await embedder.encode(["warm up"])
        start_ups.append(
            {
                "start_to_ready_s": round(embedder.start_seconds, 2),
                "import_ms": embedder.ready["import_ms"],
                "load_ms": embedder.ready["load_ms"],
            }
        )
        if resident is None:
            resident = embedder
        else:
            await embedder.close()
    assert resident is not None
    singles: list[float] = []
    for query in queries:
        began = time.perf_counter()
        await resident.encode([query.text])
        singles.append((time.perf_counter() - began) * 1000)
    batch = texts[:64]
    began = time.perf_counter()
    await resident.encode(batch)
    batch_ms = (time.perf_counter() - began) * 1000
    counts = await resident.token_counts(texts)
    window = int(resident.ready["max_seq_length"])
    await resident.close()
    return {
        "model_id": model_id,
        "dimension": resident.ready["dimension"],
        "max_seq_length": window,
        "starts": start_ups,
        "resident_query_embed_ms": latency_summary([value / 1000 for value in singles]),
        "resident_batch_64_docs_ms": round(batch_ms, 1),
        "docs_per_second_batched": round(len(batch) / (batch_ms / 1000), 1),
        "record_texts": len(texts),
        "tokens_max": max(counts),
        "tokens_p95": sorted(counts)[int(0.95 * (len(counts) - 1))],
        "texts_over_window": sum(1 for count in counts if count > window),
    }


def record_texts(records: list[FixtureRecord]) -> list[str]:
    """The text each record contributes to a semantic index: title and body."""
    return [document_text(record.title, record.body) for record in records]


def _du_kb(path: Path, *, follow: bool = False) -> int:
    outcome = subprocess.run(
        ["du", "-skL" if follow else "-sk", str(path)], capture_output=True, text=True, check=False
    )
    return int(outcome.stdout.split()[0]) if outcome.returncode == 0 else -1


def model_cache_kb(model_id: str) -> int:
    """Disk used by a model in the Hugging Face cache."""
    folder = Path(HF_HOME) / "hub" / f"models--{model_id.replace('/', '--')}"
    return _du_kb(folder, follow=True)


def vectra_env_kb() -> int:
    """Vectra's tool environment (interpreter, torch, sentence-transformers, LanceDB)."""
    return _du_kb(Path("/home/phzamora/.local/share/uv/tools/vectra"))


def arm_store_kb(ctx: ArmContext) -> dict[str, int]:
    """Disk used by the arm's own store: Vectra data and the per-revision files."""
    base = ctx.workdir / "vectra-arm"
    return {
        "vectra_lancedb_kb": _du_kb(base / "vectra-data") if base.exists() else 0,
        "revision_files_kb": _du_kb(base / "state") if base.exists() else 0,
    }


def neo4j_container_id(settings: Neo4jConnectionSettings) -> str | None:
    """The testcontainers container serving `settings` (matched by its published Bolt port)."""
    port = settings.uri.rsplit(":", 1)[-1]
    listing = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}} {{.Ports}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in listing.splitlines():
        identifier, _, ports = line.partition(" ")
        if f":{port}->7687" in ports:
            return identifier
    return None


def neo4j_disk_kb(settings: Neo4jConnectionSettings) -> dict[str, int]:
    """Size of the test container's database folders (schema indexes, whole database)."""
    identifier = neo4j_container_id(settings)
    if identifier is None:
        return {}
    sizes: dict[str, int] = {}
    for name, path in (
        ("schema_index_kb", "/data/databases/neo4j/schema/index"),
        ("database_kb", "/data/databases/neo4j"),
    ):
        outcome = subprocess.run(
            ["docker", "exec", identifier, "du", "-sk", path],
            capture_output=True,
            text=True,
            check=False,
        )
        sizes[name] = int(outcome.stdout.split()[0]) if outcome.returncode == 0 else -1
    return sizes


async def checkpoint(env: Neo4jKnowledgeEnv) -> None:
    """Flush Neo4j's index files so their size on disk is representative."""
    try:
        async with await env.client.begin() as transaction:
            await transaction.run("CALL db.checkpoint()")
    except Exception as error:  # best effort, sizes are informative
        print(f"checkpoint skipped: {error}", file=sys.stderr)
    await asyncio.sleep(1)


def point_hf_cache() -> None:
    """Child processes find the models in the user's existing cache (no download)."""
    os.environ["HF_HOME"] = HF_HOME
