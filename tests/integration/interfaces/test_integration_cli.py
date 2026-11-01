"""`noesis integrate claude-code` and `noesis skills` end to end."""

import json
from pathlib import Path

import pytest

from noesis.interfaces.cli import (
    run,
)

pytestmark = pytest.mark.integration

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


def test_install_previews_then_writes_with_a_backup_and_uninstall_restores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings: Path = tmp_path / "settings.json"
    original: str = '{"model": "opus"}'
    settings.write_text(original, encoding="utf-8")
    command: str = "/opt/noesis hook claude-code"

    assert (
        run(
            [
                "integrate",
                "claude-code",
                "install",
                "--settings",
                str(settings),
                "--command",
                command,
            ]
        )
        == 0
    )
    assert "Preview only" in capsys.readouterr().out
    assert settings.read_text() == original

    assert (
        run(
            [
                "integrate",
                "claude-code",
                "install",
                "--settings",
                str(settings),
                "--command",
                command,
                "--yes",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)["result"]
    assert (result["applied"], result["installed"]["Stop"]) == (True, [command])
    assert Path(result["backup"]).read_text() == original
    assert json.loads(settings.read_text())["model"] == "opus"

    assert (
        run(
            [
                "integrate",
                "claude-code",
                "install",
                "--settings",
                str(settings),
                "--command",
                command,
                "--yes",
            ]
        )
        == 0
    )
    assert "already up to date" in capsys.readouterr().out

    assert run(["integrate", "claude-code", "status", "--settings", str(settings)]) == 0
    assert ": installed" in capsys.readouterr().out

    assert run(["integrate", "claude-code", "uninstall", "--settings", str(settings), "--yes"]) == 0
    capsys.readouterr()
    assert json.loads(settings.read_text()) == {"model": "opus"}
    assert run(["integrate", "claude-code", "status", "--settings", str(settings)]) == 0
    assert "missing PostToolUse, Stop, SessionEnd" in capsys.readouterr().out


def test_install_into_a_missing_file_creates_it_and_detects_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings: Path = tmp_path / "new" / "settings.json"

    assert (
        run(["integrate", "claude-code", "install", "--settings", str(settings), "--yes", "--json"])
        == 0
    )

    result = json.loads(capsys.readouterr().out)["result"]
    assert result["backup"] is None
    assert result["command"].endswith("noesis hook claude-code")
    assert settings.is_file()


def test_invalid_settings_are_reported_not_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings: Path = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    assert (
        run(["integrate", "claude-code", "install", "--settings", str(settings), "--yes", "--json"])
        == 1
    )

    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "INTEGRATION_101_AGENT_SETTINGS_INVALID"
    )
    assert settings.read_text() == "{not json"


def test_skills_list_and_get_serve_the_packaged_guide(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["skills", "list", "--json"]) == 0
    assert [guide["name"] for guide in json.loads(capsys.readouterr().out)["result"]["guides"]] == [
        "noesis"
    ]

    assert run(["skills", "get", "noesis"]) == 0
    guide: str = capsys.readouterr().out
    assert guide.startswith("# noesis: guide for agents")
    assert "capture on --session" in guide

    assert run(["skills", "get", "nope", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["metadata"]["available"] == ["noesis"]


def test_the_installable_skill_stub_defers_to_the_cli_guide() -> None:
    stub: str = (PROJECT_ROOT / "skills/noesis/SKILL.md").read_text(encoding="utf-8")

    assert stub.startswith("---\nname: noesis\ndescription: ")
    assert "noesis skills get noesis" in stub
    assert "${CLAUDE_SESSION_ID}" in stub
    assert ".claude/settings.local.json" in stub
    assert "noesis --env-file <path> capture on" in stub


def test_the_guide_pins_the_hooks_env_file_and_verifies_capture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(["skills", "get", "noesis"])
    guide: str = capsys.readouterr().out

    assert "## Which env file" in guide
    assert "noesis [--env-file <path>] capture on --session" in guide
    assert "`result.enabled` is `true`" in guide


def test_every_command_in_the_guide_exists(capsys: pytest.CaptureFixture[str]) -> None:
    run(["skills", "get", "noesis"])
    guide: str = capsys.readouterr().out
    commands: set[tuple[str, str]] = set()
    in_code: bool = False
    for line in guide.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif in_code and line.startswith("noesis "):
            words: list[str] = line.replace("[--env-file <path>] ", "").split()
            if len(words) > 2 and not words[2].startswith(("-", "<", '"')):
                commands.add((words[1], words[2]))
    assert len(commands) >= 10
    for group, command in commands:
        assert run([group, command, "--help"]) == 0, f"noesis {group} {command}"
    capsys.readouterr()


def test_the_default_settings_file_follows_claude_config_dir(
    isolated_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        run(
            ["integrate", "claude-code", "install", "--command", "noesis hook claude-code", "--yes"]
        )
        == 0
    )
    capsys.readouterr()

    assert (isolated_environment / ".claude/settings.json").is_file()
    assert run(["doctor", "--json"]) in (0, 1)
    checks = json.loads(capsys.readouterr().out)["result"]["checks"]
    hooks = next(check for check in checks if check["name"] == "claude_code_hooks")
    assert hooks["detail"] == "installed: PostToolUse, SessionEnd, Stop"


def test_doctor_reports_unreadable_agent_settings_as_a_failed_check(
    isolated_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings: Path = isolated_environment / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")

    assert run(["doctor", "--json"]) == 1

    checks = json.loads(capsys.readouterr().out)["result"]["checks"]
    hooks = next(check for check in checks if check["name"] == "claude_code_hooks")
    assert hooks["ok"] is False
    assert hooks["detail"] == f"{settings} is not valid JSON"
