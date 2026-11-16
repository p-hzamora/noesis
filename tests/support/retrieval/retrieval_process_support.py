"""Subprocess helpers for the Retrieval e2e tests: other working directories, polling, a dead store."""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from pydantic import SecretStr
from tests.support.knowledge_cli_support import closed_port
from tests.support.knowledge_neo4j_support import query
from tests.support.noesis_process_support import (
    ProcessResult,
    finish,
    store_environment,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

CONNECT_TIMEOUT_SECONDS: Final[str] = "2"
POLL_TIMEOUT_SECONDS: Final[float] = 60.0
POLL_INTERVAL_SECONDS: Final[float] = 0.05
ACTIVE_SPACE: Final[str] = "default"
SECRET: Final[str] = "s3cret-pw-never-printed"


def start_noesis_in(
    cwd: Path, args: list[str], env: dict[str, str], *, json_output: bool = True
) -> subprocess.Popen[str]:
    """`python -m noesis` in `cwd` (a git repository, a plain folder...), like `start_noesis`."""
    env_file: Path = Path(env["HOME"]) / "empty.env"
    env_file.touch()
    tail: list[str] = ["--json"] if json_output else []
    return subprocess.Popen(
        [sys.executable, "-m", "noesis", "--env-file", str(env_file), *args, *tail],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_noesis_in(
    cwd: Path, args: list[str], env: dict[str, str], *, json_output: bool = True
) -> ProcessResult:
    """Run one production `noesis` command to completion with `cwd` as working directory."""
    started: float = time.monotonic()
    return finish(start_noesis_in(cwd, args, env, json_output=json_output), started)


def closed_store_environment(home: Path, space: str = ACTIVE_SPACE) -> dict[str, str]:
    """A child environment whose Neo4j port nothing listens on (the store is "down")."""
    settings = Neo4jConnectionSettings(
        uri=f"bolt://127.0.0.1:{closed_port()}", user="neo4j", password=SecretStr(SECRET)
    )
    return {
        **store_environment(home, space, settings),
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": CONNECT_TIMEOUT_SECONDS,
    }


def wait_until(
    condition: Callable[[], bool],
    what: str,
    *,
    process: subprocess.Popen[str] | None = None,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> None:
    """Poll `condition` until true; fail with `what` on timeout or when `process` ended first."""
    deadline: float = time.monotonic() + timeout
    while not condition():
        if process is not None and process.poll() is not None:
            raise AssertionError(f"the process ended before: {what}")
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for: {what}")
        time.sleep(POLL_INTERVAL_SECONDS)


def probe_count(settings: Neo4jConnectionSettings) -> int:
    """How many `:IndexProbe` nodes exist."""
    return int(query(settings, "MATCH (p:IndexProbe) RETURN count(p) AS total")[0]["total"])


def probe_snapshot(settings: Neo4jConnectionSettings) -> list[tuple[str, int | None, str | None]]:
    """Every `:IndexProbe` as (key, revision, status), sorted by key."""
    rows = query(
        settings,
        "MATCH (p:IndexProbe) RETURN p.key AS key, p.revision AS revision, p.status AS status "
        "ORDER BY key",
    )
    return [(row["key"], row["revision"], row["status"]) for row in rows]


def probe_cursor(settings: Neo4jConnectionSettings, space_id: str) -> int | None:
    """The `probe` cursor's sequence for a space, or None when it does not exist."""
    rows = query(
        settings,
        "MATCH (c:IndexCursor {cursor_key: $key}) RETURN c.sequence AS sequence",
        key=f"probe:{space_id}",
    )
    return rows[0]["sequence"] if rows else None


def head_sequence(settings: Neo4jConnectionSettings, space_id: str) -> int:
    """The change counter of a space (0 when no change was ever appended)."""
    rows = query(
        settings,
        "MATCH (c:ChangeCounter {space_id: $space_id}) RETURN c.value AS value",
        space_id=space_id,
    )
    return int(rows[0]["value"]) if rows else 0


def space_id_of(settings: Neo4jConnectionSettings, key: str = ACTIVE_SPACE) -> str:
    """The id of the space with this key."""
    return str(query(settings, "MATCH (s:Space {key: $key}) RETURN s.id AS id", key=key)[0]["id"])


def revise_command(record_id: str, key: str, body: str, expected: int = 1) -> list[str]:
    """A valid `record revise` command line (without `--json`)."""
    return [
        "record",
        "revise",
        record_id,
        "--expected-revision",
        str(expected),
        "--body",
        body,
        "--idempotency-key",
        key,
    ]
