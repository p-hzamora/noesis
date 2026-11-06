"""`noesis capture` and `noesis hook claude-code` end to end (dry-run mode, real git and files)."""

import io
import json
import subprocess
from pathlib import Path

import pytest
from tests.support.git_support import add_worktree, commit, isolate_git

from noesis.interfaces.cli import (
    run,
)
from noesis.interfaces.cli.commands import capture_commands

pytestmark = pytest.mark.integration

SESSION: str = "cli-session-1"


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "state"
    monkeypatch.setenv("NOESIS_STATE_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CAPTURE_MIN_FILES", "1")
    return folder


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository called `repo`; it is also the working directory, as for a real session."""
    folder: Path = tmp_path / "repo"
    folder.mkdir()
    monkeypatch.chdir(folder)
    git = ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    (folder / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "feat: a"], check=True)
    return folder


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    path: Path = tmp_path / "t.jsonl"
    lines = [
        {"message": {"role": "user", "content": "add a"}},
        {
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Write", "input": {}}],
            }
        },
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def _hook(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object] | str) -> int:
    text: str = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return run(["hook", "claude-code"])


def test_capture_on_then_hooks_hand_over_and_runs_shows_the_journal(
    state: Path,
    repo: Path,
    transcript: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["enabled"] is True

    commit = {
        "session_id": SESSION,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    assert _hook(monkeypatch, commit) == 0
    assert _hook(monkeypatch, {**commit, "tool_input": {"command": "git status"}}) == 0
    assert run(["capture", "status", "--session", SESSION]) == 0
    assert "pending: 1 commit(s)" in capsys.readouterr().out

    assert (
        _hook(
            monkeypatch,
            {"session_id": SESSION, "hook_event_name": "Stop", "transcript_path": str(transcript)},
        )
        == 0
    )
    assert capsys.readouterr().out == ""  # hooks print nothing

    assert run(["capture", "runs", "--session", SESSION, "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)["result"]["runs"]
    assert [entry["outcome"] for entry in runs] == ["enabled", "marked", "handed_over"]
    brief = json.loads(Path(runs[-1]["reference"]).read_text())
    assert (brief["repository"], brief["goal"]) == ("repo", "add a")

    assert run(["capture", "off", "--session", SESSION]) == 0
    assert "off" in capsys.readouterr().out


def test_hooks_ignore_garbage_unknown_events_and_their_own_curator_run(
    state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _hook(monkeypatch, "not json") == 0
    assert _hook(monkeypatch, {"session_id": SESSION, "hook_event_name": "UserPromptSubmit"}) == 0
    monkeypatch.setenv("NOESIS_HOOK", "1")
    assert _hook(monkeypatch, {"session_id": SESSION, "hook_event_name": "Stop"}) == 0
    assert capsys.readouterr() == ("", "") or True
    assert not state.exists()  # nothing was even opened


def test_hook_failures_are_logged_never_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("NOESIS_CAPTURE_MIN_LINES", "-1")  # invalid configuration

    assert _hook(monkeypatch, {"session_id": SESSION, "hook_event_name": "Stop"}) == 0
    log: Path = tmp_path / "home/.local/state/noesis/capture/hook-errors.log"
    assert "InvalidConfigurationError" in log.read_text()


def test_capture_needs_a_session_from_somewhere(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "status", "--json"]) == 2  # a flag the caller can fix: usage error
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CAPTURE_202_SESSION_ID_MISSING"


@pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "spaces"])
@pytest.mark.parametrize("command", ["on", "off", "status", "runs"])
def test_a_blank_session_is_a_usage_error_before_any_side_effect(
    command: str,
    blank: str,
    state: Path,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", "ambient")  # a blank flag must not fall back to it

    assert run(["capture", command, "--session", blank, "--json"]) == 2

    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "INTERFACE_003_BLANK_SESSION_ID"
    assert error["next_steps"]
    assert not state.exists()  # nothing was opened or registered


@pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "spaces"])
def test_a_blank_parent_is_a_usage_error_and_never_resolves_to_the_ambient_id(
    blank: str,
    state: Path,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("NOESIS_SESSION_ID", SESSION)  # the ambient id would be a valid parent

    assert run(["capture", "on", "--session", "child", "--parent", blank, "--json"]) == 2

    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "INTERFACE_003_BLANK_SESSION_ID"
    assert error["metadata"]["option"] == "--parent"


def test_a_session_cannot_be_its_own_parent_and_that_is_a_usage_error(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    capsys.readouterr()

    assert run(["capture", "on", "--session", SESSION, "--parent", SESSION, "--json"]) == 2

    assert (
        json.loads(capsys.readouterr().out)["error"]["code"] == "INTERFACE_004_SELF_PARENT_SESSION"
    )


@pytest.fixture
def outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "plain"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


@pytest.mark.parametrize("command", ["on", "off", "status", "runs"])
def test_every_capture_command_outside_a_repository_fails_like_notes(
    command: str, state: Path, outside: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", command, "--session", SESSION, "--json"]) == 2

    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "INTERFACE_002_NOT_IN_GIT_REPOSITORY"
    assert not state.exists()


def test_a_generated_session_id_is_flagged_in_the_result_and_warned_about_on_stderr(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--mode", "dry-run", "--json"]) == 0
    captured = capsys.readouterr()
    fresh: str = json.loads(captured.out)["result"]["session_id"]
    assert json.loads(captured.out)["result"]["generated"] is True
    assert "generated" in captured.err and fresh in captured.err
    assert "--session" in captured.err

    assert run(["capture", "status", "--session", fresh, "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["result"]["generated"] is False  # nothing was generated now
    assert captured.err == ""


def test_an_explicit_or_ambient_session_id_is_not_flagged_and_prints_no_warning(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--json"]) == 0
    captured = capsys.readouterr()
    assert (json.loads(captured.out)["result"]["generated"], captured.err) == (False, "")

    monkeypatch.setenv("NOESIS_SESSION_ID", "ambient")
    assert run(["capture", "on", "--json"]) == 0
    captured = capsys.readouterr()
    assert (json.loads(captured.out)["result"]["generated"], captured.err) == (False, "")


def test_queries_never_write_the_repository_registry_but_enable_does(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry: Path = state / "capture" / "repos.json"

    assert run(["capture", "status", "--session", SESSION, "--json"]) == 0
    assert run(["capture", "runs", "--session", SESSION, "--json"]) == 0
    assert not registry.exists()

    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    assert str(repo) in registry.read_text()


def test_a_blank_ambient_id_counts_as_absent(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", "   ")

    assert run(["capture", "on", "--json"]) == 0  # a fresh id is chosen
    assert json.loads(capsys.readouterr().out)["result"]["generated"] is True
    assert run(["capture", "status", "--json"]) == 2  # and nothing identifies the session
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CAPTURE_202_SESSION_ID_MISSING"


def test_capture_on_with_a_parent_builds_the_handlers_and_runs_the_loop_once(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    capsys.readouterr()
    builds: list[object] = []
    loops: list[object] = []
    real_build = capture_commands.build_capture
    real_run = capture_commands.asyncio.run

    def counting_build(environment: object) -> object:
        builds.append(environment)
        return real_build(environment)  # type: ignore[arg-type]

    def counting_run(coroutine: object) -> object:
        loops.append(coroutine)
        return real_run(coroutine)  # type: ignore[arg-type]

    monkeypatch.setattr(capture_commands, "build_capture", counting_build)
    monkeypatch.setattr(capture_commands.asyncio, "run", counting_run)

    assert run(["capture", "on", "--session", "child", "--parent", SESSION, "--json"]) == 0

    assert (len(builds), len(loops)) == (1, 1)


def test_an_odd_session_id_is_hashed_into_a_safe_one_not_rejected(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "status", "--session", "bad id/../x", "--json"]) == 0

    stored: str = json.loads(capsys.readouterr().out)["result"]["session_id"]
    assert stored.startswith("repo-") and "/" not in stored and " " not in stored


def test_capture_on_reports_the_env_file_state_dir_and_vault_the_hooks_must_share(
    tmp_path: Path,
    repo: Path,
    transcript: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned_state: Path = tmp_path / "lab/state"
    env_file: Path = tmp_path / "lab/noesis.env"
    env_file.parent.mkdir()
    env_file.write_text(
        f"NOESIS_STATE_DIR={pinned_state}\nNOESIS_VAULT_DIR={tmp_path / 'lab/vault'}\n"
        "NOESIS_CAPTURE_MIN_FILES=1\n",
        encoding="utf-8",
    )
    pinned: list[str] = ["--env-file", str(env_file)]

    assert run([*pinned, "capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert (result["enabled"], result["env_file"], result["state_dir"], result["vault_dir"]) == (
        True,
        str(env_file),
        str(pinned_state),
        str(tmp_path / "lab/vault"),
    )

    # Without the pinned env file, the default state dir knows nothing about the session.
    assert run(["capture", "status", "--session", SESSION, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["enabled"] is False

    commit = {
        "session_id": SESSION,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(repo),
        "transcript_path": str(transcript),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(commit)))
    assert run([*pinned, "hook", "claude-code"]) == 0
    assert run([*pinned, "capture", "status", "--session", SESSION]) == 0
    text: str = capsys.readouterr().out
    assert "pending: 1 commit(s)" in text
    assert f"state dir: {pinned_state}" in text


def _stored_id(capsys: pytest.CaptureFixture[str]) -> str:
    return json.loads(capsys.readouterr().out)["result"]["session_id"]


def test_a_bare_capture_on_prints_a_fresh_id_that_can_be_passed_back(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--mode", "dry-run", "--json"]) == 0
    fresh: str = _stored_id(capsys)

    assert run(["capture", "on", "--json"]) == 0
    other: str = _stored_id(capsys)
    assert fresh != other  # nothing identified the session, so each call starts a new one

    assert run(["capture", "status", "--session", fresh, "--json"]) == 0
    status = json.loads(capsys.readouterr().out)["result"]
    assert (status["session_id"], status["enabled"], status["mode"]) == (fresh, True, "dry-run")


def test_the_ambient_session_id_is_used_when_no_session_is_given(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", SESSION)
    assert run(["capture", "on", "--json"]) == 0
    from_env: str = _stored_id(capsys)
    monkeypatch.delenv("NOESIS_SESSION_ID")

    assert run(["capture", "on", "--session", SESSION, "--json"]) == 0
    assert _stored_id(capsys) == from_env  # the CLI and the variable agree


def test_a_repeat_capture_on_keeps_the_pending_work(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run"]) == 0
    commit = {
        "session_id": SESSION,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(repo),
    }
    assert _hook(monkeypatch, commit) == 0
    capsys.readouterr()

    assert run(["capture", "on", "--session", SESSION, "--json"]) == 0

    status = json.loads(capsys.readouterr().out)["result"]
    assert (status["mode"], status["pending_commits"]) == ("dry-run", 1)


def test_a_child_session_inherits_the_mode_and_its_runs_merge_with_the_parents(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    parent: str = _stored_id(capsys)

    assert run(["capture", "on", "--parent", parent, "--json"]) == 0
    child = json.loads(capsys.readouterr().out)["result"]
    assert (child["parent_id"], child["mode"], child["enabled"]) == (parent, "dry-run", True)
    assert child["session_id"] != parent  # a sub-agent never reuses the parent's id

    assert run(["capture", "runs", "--session", parent, "--children", "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)["result"]
    assert runs["children"] == [child["session_id"]]
    assert {entry["session_id"] for entry in runs["runs"]} == {parent, child["session_id"]}


def test_a_parent_that_was_never_switched_on_is_an_error(
    state: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["capture", "on", "--parent", "ghost", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CAPTURE_201_SESSION_NOT_FOUND"


def test_a_commit_in_a_linked_worktree_is_captured_when_the_hook_reports_the_main_checkout(
    state: Path,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    isolate_git(monkeypatch)
    linked = add_worktree(repo, tmp_path / "repo-feature", "feat/x")
    assert run(["capture", "on", "--session", SESSION, "--mode", "dry-run", "--json"]) == 0
    capsys.readouterr()
    sha = commit(linked, "work.txt")
    payload = {
        "session_id": SESSION,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": f"cd {linked} && git commit -m work.txt"},
        "cwd": str(repo),  # Claude reports the main checkout, not the worktree
    }

    assert _hook(monkeypatch, payload) == 0

    assert run(["capture", "runs", "--session", SESSION, "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)["result"]["runs"]
    assert [entry["outcome"] for entry in runs] == ["enabled", "marked"]
    assert sha[:8] in runs[-1]["detail"]


def test_codex_thread_id_identifies_the_session_without_any_flag(
    state: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "01a1b0df-ec32-7ae1-8f6a-4975af14425b")
    monkeypatch.setenv("CODEX_SESSION_ID", "01a1b0df-ec32-7ae1-8f6a-4975af14425b")
    monkeypatch.setenv("CODEX_TOOL_CALL_ID", "call-changes-every-time")
    assert run(["capture", "on", "--json"]) == 0
    first: str = _stored_id(capsys)

    assert run(["capture", "on", "--json"]) == 0  # a later call in the same thread

    assert _stored_id(capsys) == first
    assert run(["capture", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["enabled"] is True
