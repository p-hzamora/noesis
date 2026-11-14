"""Helpers to drive `record`, `store` and `doctor` in-process against a real or closed Neo4j."""

import json
import socket
from collections.abc import Sequence

import pytest

from noesis.interfaces.cli import run
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

IDEMPOTENCY_KEY: str = "test-key-1"
COMMIT_SOURCE: str = "commit:" + "a" * 40
CONNECT_TIMEOUT_SECONDS: str = "2"


def closed_port() -> int:
    """A localhost port nothing listens on (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def use_store(monkeypatch: pytest.MonkeyPatch, settings: Neo4jConnectionSettings) -> None:
    """Point this test process (never the user's profile) at `settings`."""
    monkeypatch.setenv("NOESIS_NEO4J_URI", settings.uri)
    monkeypatch.setenv("NOESIS_NEO4J_USER", settings.user)
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", settings.password.get_secret_value())
    monkeypatch.setenv("NOESIS_NEO4J_DATABASE", settings.database)


def use_closed_store(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point at a closed local port with a password set; returns the URI."""
    uri: str = f"bolt://127.0.0.1:{closed_port()}"
    monkeypatch.setenv("NOESIS_NEO4J_URI", uri)
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", "never-sent")
    monkeypatch.setenv("NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS", CONNECT_TIMEOUT_SECONDS)
    return uri


def run_json(
    capsys: pytest.CaptureFixture[str], argv: Sequence[str]
) -> tuple[int, dict[str, object]]:
    """Run one command with `--json`; returns the exit code and the parsed envelope."""
    code: int = run([*argv, "--json"])
    out: str = capsys.readouterr().out
    envelope: object = json.loads(out) if out.strip() else {}
    assert isinstance(envelope, dict)
    return code, envelope


def capture_args(
    key: str = IDEMPOTENCY_KEY, *, title: str = "Retry policy", body: str = "Use retries."
) -> list[str]:
    """A valid knowledge capture command line."""
    return [
        "record",
        "capture",
        "--type",
        "knowledge",
        "--title",
        title,
        "--body",
        body,
        "--subtype",
        "decision",
        "--project",
        "demo",
        "--tag",
        "area:retries",
        "--source",
        COMMIT_SOURCE,
        "--idempotency-key",
        key,
    ]
