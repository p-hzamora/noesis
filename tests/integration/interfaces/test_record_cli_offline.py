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
    IDEMPOTENCY_KEY,
    capture_args,
    run_json,
    use_closed_store,
)

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration

ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"

ALL_STORE_COMMANDS: list[list[str]] = [
    capture_args(),
    [
        "record",
        "capture",
        "--type",
        "experience",
        "--body",
        "It failed.",
        "--subtype",
        "failure",
        "--source",
        "agent_session:s-1",
        "--idempotency-key",
        IDEMPOTENCY_KEY,
    ],
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


@pytest.mark.parametrize(
    "argv",
    [
        [a for a in capture_args() if a not in ("--idempotency-key", "test-key-1")],
        ["record", "revise", ID, "--expected-revision", "1", "--body", "x"],
    ],
    ids=["capture", "revise"],
)
def test_a_missing_idempotency_key_is_a_usage_error_that_touches_nothing(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # a closed port AND no password: any attempt to load the store settings or connect would
    # fail with a different code and exit 1
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://127.0.0.1:1")

    assert run(argv) == 2

    assert "--idempotency-key" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["record", "capture", "--idempotency-key", "k"],  # no --type
        ["record", "capture", "--type", "knowledge", "--idempotency-key", "k", "--body", "b"],
        [  # no source
            "record",
            "capture",
            "--type",
            "knowledge",
            "--idempotency-key",
            "k",
            "--title",
            "t",
            "--subtype",
            "decision",
            "--body",
            "b",
        ],
        [  # malformed source
            *capture_args(),
            "--source",
            "nocolon",
        ],
        [*capture_args(), "--source", "bogus:thing"],
        [  # experience without a source
            "record",
            "capture",
            "--type",
            "experience",
            "--idempotency-key",
            "k",
            "--body",
            "b",
        ],
        [
            "record",
            "capture",
            "--type",
            "experience",
            "--idempotency-key",
            "k",
            "--source",
            "commit:a",
        ],
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
        ["record", "capture", "--help"],
        ["store", "init", "--help"],
    ):
        assert run(argv) == 0
    assert "--idempotency-key" in run_help(capsys)


def run_help(capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    run(["record", "capture", "--help"])
    return capsys.readouterr().out


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
