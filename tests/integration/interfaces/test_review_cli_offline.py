"""`assertion` and `review` without a reachable store, in-process.

Usage errors exit 2 before any I/O (a closed port is configured, so any attempt would exit 1 with
`INTEGRATION_103` instead); the user-presence and bulk-authority refusals come before the store
(AC-023, AC-027, AC-028); an invalid tag fails like `record capture --tag` does.
"""

import pytest
from tests.support.knowledge_cli_support import capture_args, run_json, use_closed_store
from tests.support.review_support import AGENT_SESSION, attach_terminal

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration

ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
OTHER_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
TAG = "origin:migrated"

PROPOSE = [
    "assertion",
    "propose",
    "--predicate",
    "supports",
    "--subject",
    ID,
    "--object",
    OTHER_ID,
    "--rationale",
    "because",
    "--source",
    "agent_session:s1",
    "--idempotency-key",
    "k",
]


def _without(argv: list[str], option: str) -> list[str]:
    """`argv` minus `option` and its value."""
    index = argv.index(option)
    return [*argv[:index], *argv[index + 2 :]]


USAGE_ERRORS: dict[str, list[str]] = {
    "queue project and global": ["review", "queue", "--project", "acme", "--global"],
    "retract without reason": ["review", "retract", ID, "--yes", "--idempotency-key", "k"],
    "retract yes without key": ["review", "retract", ID, "--reason", "r", "--yes"],
    "accept yes without key": ["review", "accept", ID, "--yes"],
    "propose without source": _without(PROPOSE, "--source"),
    "propose without rationale": _without(PROPOSE, "--rationale"),
    "propose without predicate": _without(PROPOSE, "--predicate"),
    "propose without key": _without(PROPOSE, "--idempotency-key"),
    "propose unknown predicate": [*_without(PROPOSE, "--predicate"), "--predicate", "likes"],
    "queue limit zero": ["review", "queue", "--limit", "0"],
    "list without about": ["assertion", "list"],
}
BULK_USAGE_ERRORS: dict[str, list[str]] = {
    "tag without all": ["review", "accept", "--tag", TAG],
    "all without tag": ["review", "accept", "--all"],
    "id with tag": ["review", "accept", ID, "--tag", TAG, "--all"],
    "expected revision with tag": [
        "review",
        "accept",
        "--tag",
        TAG,
        "--all",
        "--expected-revision",
        "1",
    ],
    "key with tag": ["review", "accept", "--tag", TAG, "--all", "--yes", "--idempotency-key", "k"],
    "neither id nor tag": ["review", "accept"],
}


@pytest.mark.parametrize(
    "argv",
    [*USAGE_ERRORS.values(), *BULK_USAGE_ERRORS.values()],
    ids=[*USAGE_ERRORS, *BULK_USAGE_ERRORS],
)
def test_usage_errors_exit_2_with_a_closed_port_and_do_no_io(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_closed_store(monkeypatch)

    assert run(argv) == 2


def test_an_invalid_bulk_tag_fails_like_capture_does_and_before_the_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    capture_code, capture = run_json(capsys, [*capture_args(), "--tag", "Bad Tag!"])
    bulk_code, bulk = run_json(capsys, ["review", "accept", "--tag", "Bad Tag!", "--all"])

    capture_error = capture["error"]
    bulk_error = bulk["error"]
    assert isinstance(capture_error, dict) and isinstance(bulk_error, dict)
    assert capture_code == bulk_code == 1
    assert bulk_error["code"] == capture_error["code"]
    assert bulk_error["code"] != "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


def _error(envelope: dict[str, object]) -> dict[str, object]:
    error = envelope["error"]
    assert isinstance(error, dict)
    return error


APPLYING = {
    "accept": [
        "review",
        "accept",
        ID,
        "--expected-revision",
        "1",
        "--yes",
        "--idempotency-key",
        "k",
    ],
    "retract": ["review", "retract", ID, "--reason", "x", "--yes", "--idempotency-key", "k"],
    "bulk": ["review", "accept", "--tag", TAG, "--all", "--yes"],
}


@pytest.mark.parametrize("argv", APPLYING.values(), ids=APPLYING)
def test_ac023_ac028_the_user_without_a_terminal_is_refused_before_the_store(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    attach_terminal(monkeypatch, tty=False)

    code, envelope = run_json(capsys, argv)

    assert code == 1
    assert _error(envelope)["code"] == "INTERFACE_006_USER_PRESENCE_REQUIRED"  # not INTEGRATION_103
    assert _error(envelope)["next_steps"]


@pytest.mark.parametrize(
    "argv",
    [
        APPLYING["accept"],
        APPLYING["retract"],
        ["review", "accept", ID, "--expected-revision", "1"],
        ["review", "accept", "--tag", TAG, "--all"],
    ],
    ids=["accept as agent", "retract as agent", "preview as user", "bulk preview as user"],
)
def test_ac023_controls_do_not_raise_the_presence_error(
    argv: list[str],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    attach_terminal(monkeypatch, tty=False)
    if "agent" in request.node.callspec.id:
        monkeypatch.setenv("NOESIS_SESSION_ID", AGENT_SESSION)

    code, envelope = run_json(capsys, argv)

    assert code == 1  # the closed port: the command got as far as the store
    assert _error(envelope)["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


def test_ac027_an_agent_applying_the_bulk_accept_is_refused_before_the_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_SESSION_ID", AGENT_SESSION)

    code, envelope = run_json(capsys, APPLYING["bulk"])

    error = _error(envelope)
    assert code == 1
    assert error["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert error["metadata"]["reason"] == "bulk_accept_requires_user"  # type: ignore[index]
    assert error["next_steps"]
