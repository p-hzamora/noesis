"""One CLI component decides `agent` or `user`; no option can claim `user` (D-024, A-14)."""

import pytest

from noesis.core import load_environment
from noesis.interfaces.cli import run
from noesis.interfaces.cli.actor import resolve_actor

pytestmark = pytest.mark.unit


def _actor(monkeypatch: pytest.MonkeyPatch, **variables: str):
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    return resolve_actor(load_environment().identity)


def test_no_harness_marker_means_the_user_named_after_the_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGNAME", "pablo")
    monkeypatch.setenv("USER", "pablo")

    actor = resolve_actor(load_environment().identity)

    assert (actor.kind.value, actor.name, actor.session) == ("user", "pablo", None)


@pytest.mark.parametrize(
    "variables",
    [
        {"CLAUDECODE": "1"},
        {"CLAUDE_CODE_SESSION_ID": "7f1c3e0a-0000-4000-8000-000000000000"},
        {"AI_AGENT": "claude-code_2-1-325_agent"},
    ],
)
def test_any_claude_code_marker_means_an_agent(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str]
) -> None:
    actor = _actor(monkeypatch, **variables)

    assert (actor.kind.value, actor.name) == ("agent", "claude-code")


def test_claude_code_session_comes_from_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = _actor(monkeypatch, CLAUDECODE="1", CLAUDE_CODE_SESSION_ID="abc-123")

    assert actor.session == "abc-123"


def test_codex_is_an_agent_with_its_thread_as_session(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = _actor(monkeypatch, CODEX_THREAD_ID="thread-9")

    assert (actor.kind.value, actor.name, actor.session) == ("agent", "codex", "thread-9")


def test_an_unknown_harness_with_a_noesis_session_id_is_an_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(monkeypatch, NOESIS_SESSION_ID="s-1")

    assert (actor.kind.value, actor.name, actor.session) == ("agent", "agent", "s-1")


def test_an_unknown_ai_agent_marker_names_the_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = _actor(monkeypatch, AI_AGENT="gemini_1-0_agent")

    assert (actor.kind.value, actor.name) == ("agent", "gemini")


def test_empty_markers_do_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER", "pablo")
    monkeypatch.setenv("LOGNAME", "pablo")

    actor = _actor(monkeypatch, CLAUDECODE="", AI_AGENT="", CODEX_THREAD_ID="")

    assert actor.kind.value == "user"


def test_no_capture_option_lets_a_caller_claim_to_be_the_user(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for option in ("--actor", "--actor-kind", "--as-user", "--user"):
        argv = ["remember", "--as", "knowledge", "--idempotency-key", "k"]
        assert run([*argv, option, "user"]) == 2
        capsys.readouterr()
    assert run(["remember", "--help"]) == 0
    help_text: str = capsys.readouterr().out
    assert "--actor" not in help_text
