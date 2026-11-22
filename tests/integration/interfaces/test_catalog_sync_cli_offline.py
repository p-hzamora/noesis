"""`catalog sync` without a reachable store: usage errors do no I/O, outages fail closed (WP-07)."""

import time

import pytest
from tests.support.knowledge_cli_support import CONNECT_TIMEOUT_SECONDS, run_json, use_closed_store

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration


def test_unknown_runtime_is_a_usage_error_that_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A closed port and no password: loading the store settings or connecting would exit 1.
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://127.0.0.1:1")

    assert run(["catalog", "sync", "--runtime", "vim"]) == 2

    assert "--runtime" in capsys.readouterr().err


def test_unknown_option_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://127.0.0.1:1")

    assert run(["catalog", "sync", "--delete"]) == 2

    assert "--delete" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [[], ["--dry-run"], ["--runtime", "codex"]], ids=str)
def test_sync_fails_closed_when_neo4j_is_down(
    flags: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    started: float = time.monotonic()

    code, envelope = run_json(capsys, ["catalog", "sync", *flags])

    assert time.monotonic() - started < float(CONNECT_TIMEOUT_SECONDS) + 3
    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
