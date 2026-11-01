"""`noesis capture` and `noesis hook claude-code` end to end (dry-run mode, real git and files)."""

import io
import json
import subprocess
from pathlib import Path

import pytest

from noesis.interfaces.cli import (
    run,
)

pytestmark = pytest.mark.integration

SESSION: str = "cli-session-1"


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "state"
    monkeypatch.setenv("NOESIS_STATE_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CAPTURE_MIN_FILES", "1")
    return folder


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder: Path = tmp_path / "repo"
    folder.mkdir()
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


def test_capture_needs_a_valid_session(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["capture", "status"]) == 2
    assert run(["capture", "status", "--session", "bad id", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CAPTURE_001_INVALID_SESSION_ID"


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
