"""`record` and `store` without a reachable store: usage errors do no I/O, outages fail closed.

Covers AC-003 at the CLI level (FR-013): every store command exits 1 with
`INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` and next steps when Neo4j is down, and usage errors
exit 2 before any settings or connection are needed.
"""

import json
import time

import pytest
from tests.support.knowledge_cli_support import (
    CONNECT_TIMEOUT_SECONDS,
    run_json,
    use_closed_store,
)

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration

ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"

ALL_STORE_COMMANDS: list[list[str]] = [
    ["record", "revise", ID, "--expected-revision", "1", "--body", "x", "--idempotency-key", "k"],
    ["record", "get", ID],
    ["store", "init"],
]


@pytest.mark.parametrize("argv", ALL_STORE_COMMANDS, ids=lambda argv: " ".join(argv[:3]))
def test_every_store_command_fails_closed_when_neo4j_is_down(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    uri: str = use_closed_store(monkeypatch)
    started: float = time.monotonic()

    code, envelope = run_json(capsys, argv)

    assert time.monotonic() - started < float(CONNECT_TIMEOUT_SECONDS) + 3
    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert error["metadata"]["uri"] == uri
    assert any("noesis doctor" in step for step in error["next_steps"])
    assert any("idempotency key" in step for step in error["next_steps"])
    assert "never-sent" not in json.dumps(envelope)


def test_text_mode_reports_the_code_and_next_steps_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)

    assert run(["record", "get", ID]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE" in captured.err
    assert "next:" in captured.err


def test_a_missing_idempotency_key_is_a_usage_error_that_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # a closed port AND no password: any attempt to load the store settings or connect would
    # fail with a different code and exit 1
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://127.0.0.1:1")

    assert run(["record", "revise", ID, "--expected-revision", "1", "--body", "x"]) == 2

    assert "--idempotency-key" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["record", "get"],
        ["record", "revise", ID, "--idempotency-key", "k"],  # no --expected-revision
    ],
)
def test_usage_errors_exit_2_without_settings_or_connection(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://127.0.0.1:1")  # closed, and no password

    assert run(argv) == 2


def test_help_never_needs_the_store(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (
        ["record", "--help"],
        ["store", "init", "--help"],
    ):
        assert run(argv) == 0


def test_revise_help_documents_the_idempotency_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["record", "revise", "--help"]) == 0

    assert "--idempotency-key" in capsys.readouterr().out


def test_a_missing_password_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, envelope = run_json(capsys, ["record", "get", ID])

    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["metadata"] == {"variable": "NOESIS_NEO4J_PASSWORD"}


def test_config_show_lists_the_knowledge_settings_with_the_password_masked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", "very-secret-value")

    code, envelope = run_json(capsys, ["config", "show"])

    assert code == 0
    assert "very-secret-value" not in json.dumps(envelope)
    knowledge = envelope["result"]["settings"]["knowledge"]  # type: ignore[index]
    assert knowledge["knowledge_space"] == "personal"
    assert knowledge["neo4j_password"] != "very-secret-value"
