"""C5b F-7: the B-bge-production arm on migrated records, plus the vector index disk weight.

Not a test: never collected by pytest or imported by `src/`. Input is a disposable COPY of a
notes vault (never the original); it is imported with `noesis import run --yes` into a
testcontainers Neo4j (pinned image) through a child process with a temporary HOME, then the
semantic projection is rebuilt through the production handlers. Only aggregate numbers are
written: no titles, bodies, paths or record identifiers leave this process.

    env -u VIRTUAL_ENV PYTHONPATH=src:. uv run --extra semantic \
        python -m scripts.retrieval_spike.bge_migrated --vault-copy <copy> --out <dir>

Migrated records have no relevance judgments: this run reports import/rebuild/lag/latency,
chunking and truncation checks, store size before and after the semantic projection, and a
controlled tail-only test record kept apart from the real-data numbers.
"""

# ruff: noqa: T201

import argparse
import asyncio
import hashlib
import json
import random
import secrets
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from testcontainers.community.neo4j import Neo4jContainer
from tests.support.neo4j_container import NEO4J_USER, TEST_CONNECT_TIMEOUT_SECONDS
from tests.support.neo4j_container import pinned_neo4j_image as pinned_image
from tests.support.noesis_process_support import _command
from tests.support.retrieval.retrieval_neo4j_support import space_id_of

from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.http_fetch import (
    https_fetch,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    ModelCache,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
    OnnxBgeEngine,
    load_engine,
)
from noesis.core.configurations.paths import default_model_cache_dir
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from .bge_production import (
    TAIL_QUERY,
    TAIL_SENTENCE,
    Arm,
    _packages,
    child_env,
    chunk_stats,
    cli_runs,
    commit_to_cursor_lag,
    during_rebuild,
    hardware,
    peak_rss_kb,
    start_embedder,
    stop,
    timed_cli,
)
from .corpus import capture, open_env
from .fixtures import FixtureRecord
from .fixtures import load_records as load_fixture
from .metrics import latency_summary

QUERY_SAMPLE = 100
PER_CALL_SAMPLES = 20
IMPORT_TIMEOUT_SECONDS = 1800
CHECKPOINT_WAIT_SECONDS = 10
STORE_DIRECTORIES = ("/data/databases/neo4j", "/data/transactions/neo4j")


@contextmanager
def neo4j_container() -> Iterator[tuple[Neo4jConnectionSettings, Neo4jContainer]]:
    """The pinned image with a random password, plus the container for size sampling."""
    password = secrets.token_urlsafe(16)
    container = Neo4jContainer(pinned_image(), username=NEO4J_USER, password=password)
    # Community has no `db.checkpoint()`: checkpoint every second so store files are current.
    container.with_env("NEO4J_db_checkpoint_interval_time", "1s")
    container.with_env("NEO4J_db_checkpoint_interval_tx", "1")
    with container:
        yield (
            Neo4jConnectionSettings(
                uri=container.get_connection_url(),
                user=NEO4J_USER,
                password=SecretStr(password),
                connect_timeout_seconds=TEST_CONNECT_TIMEOUT_SECONDS,
            ),
            container,
        )


def _du_bytes(container: Neo4jContainer, path: str) -> int:
    code, output = container.exec(["du", "-sb", path])
    if code != 0:
        return -1
    return int(output.decode().split()[0])


def _vector_index_bytes(container: Neo4jContainer) -> int:
    """Bytes of every vector index provider directory of the database (Lucene-backed)."""
    code, output = container.exec(
        ["sh", "-c", "du -sb /data/databases/neo4j/schema/index/vector-* 2>/dev/null || true"]
    )
    if code != 0:
        return -1
    return sum(int(line.split()[0]) for line in output.decode().splitlines() if line.strip())


async def store_size(arm: Arm, container: Neo4jContainer) -> dict[str, Any]:
    """After the 1 s checkpoint interval has passed, sample the store, log and index dirs."""
    await asyncio.sleep(CHECKPOINT_WAIT_SECONDS)
    sizes: dict[str, Any] = {path: _du_bytes(container, path) for path in STORE_DIRECTORIES}
    sizes["vector_index_dirs"] = _vector_index_bytes(container)
    async with await arm.env.client.begin() as transaction:
        rows = await transaction.run(
            "MATCH (e:Embedding) RETURN count(e) AS n, sum(size(e.vector)) AS floats"
        )
    sizes["embedding_nodes"] = int(rows[0]["n"])
    sizes["embedding_floats"] = int(rows[0]["floats"] or 0)
    return sizes


def corpus_checksum(vault: Path) -> dict[str, Any]:
    """SHA-256 over every Markdown file's relative path and bytes (identity only, no text)."""
    digest = hashlib.sha256()
    files = sorted(path for path in vault.rglob("*.md") if path.is_file())
    for path in files:
        digest.update(str(path.relative_to(vault)).encode())
        digest.update(path.read_bytes())
    return {"markdown_files": len(files), "sha256": digest.hexdigest()}


def run_import(env: dict[str, str]) -> dict[str, Any]:
    """`store init` then `import run --yes` in a child process; aggregate counts only."""
    home = Path(env["HOME"])
    env_file = home / "empty.env"
    env_file.touch()
    found: dict[str, Any] = {}
    for name, args in (("store_init", ["store", "init"]), ("import", ["import", "run", "--yes"])):
        started = time.perf_counter()
        process = subprocess.run(  # noqa: S603 - our own interpreter and fixed arguments
            _command(args, env_file, json_output=True),
            env=env,
            cwd=home,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_SECONDS,
            check=False,
        )
        seconds = time.perf_counter() - started
        envelope = json.loads(process.stdout) if process.stdout.strip() else {}
        if process.returncode != 0:
            code = (envelope.get("error") or {}).get("code")
            raise RuntimeError(
                f"`noesis {' '.join(args)}` failed: exit {process.returncode} {code}"
            )
        result = envelope.get("result") or {}
        found[name] = {
            "seconds": round(seconds, 2),
            "counts": {
                key: value
                for key, value in result.items()
                if isinstance(value, int | float) and not isinstance(value, bool)
            },
        }
    return found


async def record_profile(arm: Arm, space_id: str) -> tuple[dict[str, Any], list[str]]:
    """Counts by type/status/project presence, and the titles used as query texts.

    Titles stay in memory as CLI query texts; they are never written to the report.
    """
    types: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    with_project = 0
    titles: list[str] = []
    after: str | None = None
    while True:
        page = await arm.states.scan_states(space_id, after_id=after, limit=200)
        for state in page:
            types[state.record_type] += 1
            statuses[str(state.status)] += 1
            with_project += state.project_id is not None
            if state.title:
                titles.append(state.title)
        if len(page) < 200:
            break
        after = page[-1].record_id
    return (
        {
            "records_by_type": dict(types),
            "records_by_status": dict(statuses),
            "records_with_project": with_project,
        },
        titles,
    )


async def tail_control(arm: Arm, space_id: str) -> dict[str, Any]:
    """A synthetic record whose only relevant sentence is far beyond token 512 (not real data)."""
    template = load_fixture()[0]
    filler = " ".join([template.body] * 60)
    record = FixtureRecord(
        key="tail-control",
        cluster="control",
        kind="knowledge",
        subtype="decision",
        status=None,
        project=None,
        lang="en",
        title="Tail control",
        body=f"{filler} {TAIL_SENTENCE}",
        source_locator=f"{9999:040x}",
    )
    record_id = await capture(arm.env, record)
    await arm.sync(space_id)
    tokens = len(arm.engine.tokens(f"{record.title}\n{record.body}"))
    hits = await arm.source.find(TAIL_QUERY, space_id=space_id, limit=10)
    rank = next(
        (index for index, hit in enumerate(hits.hits, start=1) if hit.record_id == record_id),
        None,
    )
    return {"tokens": tokens, "tail_only_phrase_rank": rank}


def cli_latency(
    settings: Neo4jConnectionSettings, titles: list[str], cache_root: Path
) -> dict[str, Any]:
    """L (mode off), resident warm runs, search during a resident rebuild, per-call opt-in."""
    rng = random.Random(7)  # noqa: S311 - reproducible sample, not security
    pool = list(titles) or ["decision"]
    texts = [pool[rng.randrange(len(pool))] for _ in range(QUERY_SAMPLE)]
    home = Path(tempfile.mkdtemp(prefix="bgem-home-"))
    runtime = Path(tempfile.mkdtemp(prefix="nbgm-"))
    found: dict[str, Any] = {"query_texts": "record titles sampled with seed 7 (not reported)"}
    try:
        off = child_env(home, settings, cache_root, runtime, "off")
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


async def measure(
    vault: Path,
    settings: Neo4jConnectionSettings,
    container: Neo4jContainer,
    engine: OnnxBgeEngine,
    cache_root: Path,
) -> dict[str, Any]:
    home = Path(tempfile.mkdtemp(prefix="bgem-import-"))
    try:
        env = child_env(home, settings, cache_root, home / "run", "off")
        env["NOESIS_VAULT_DIR"] = str(vault)
        env["NOESIS_IMPORT_VAULT_KEY"] = "f7copy"
        print("import", flush=True)
        imported = run_import(env)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    knowledge = await open_env(settings)  # idempotent store init, retrieval steps registered
    try:
        space_id = await space_id_of(knowledge)
        arm = Arm(knowledge, engine)
        profile, titles = await record_profile(arm, space_id)
        before = await store_size(arm, container)
        print("rebuild", flush=True)
        rebuild = await arm.rebuild(space_id)
        after = await store_size(arm, container)
        stats = await chunk_stats(arm, space_id)
        print("lag", flush=True)
        lag = await commit_to_cursor_lag(knowledge, arm, space_id, load_fixture())
        print("cli", flush=True)
        cli = cli_latency(settings, titles, cache_root)
        control = await tail_control(arm, space_id)
    finally:
        await knowledge.client.close()
    store_delta = {
        path: after[path] - before[path] for path in (*STORE_DIRECTORIES, "vector_index_dirs")
    }
    return {
        "import": imported,
        "records": profile,
        "rebuild": rebuild,
        "chunks": stats,
        "store_size_bytes": {"before_rebuild": before, "after_rebuild": after},
        "store_delta_bytes": store_delta,
        "raw_vector_bytes_fp32": after["embedding_floats"] * 4,
        "lag": lag,
        "cli": cli,
        "control_tail_record": control,
    }


async def main_async(vault: Path, out: Path) -> None:
    cache_root = default_model_cache_dir()
    cache = ModelCache(cache_root)
    prepared = cache.prepare(https_fetch)
    engine = load_engine(cache)
    report: dict[str, Any] = {
        "arm": "B-bge-production",
        "corpus": "F-7 migrated records (vault copy imported with `noesis import run --yes`)",
        "corpus_identity": corpus_checksum(vault),
        "profile_hash": engine.profile.fingerprint(),
        "artifact": {"model": prepared.model, "revision": prepared.revision},
        "hardware": hardware(),
        "packages": _packages(),
        "relevance": "not measured: migrated records have no judgments",
    }
    with neo4j_container() as (settings, container):
        report["neo4j_image"] = pinned_image()
        report["f7"] = await measure(vault, settings, container, engine, cache_root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "b-bge-production-f7.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-copy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    vault: Path = args.vault_copy.resolve()
    original = (Path.home() / "brain").resolve()
    if vault == original or vault.is_relative_to(original):
        parser.error("pass a disposable copy of the vault, never the vault itself")
    asyncio.run(main_async(vault, args.out))


if __name__ == "__main__":
    main()
