"""Claude Code location settings and the env-file writer."""

from pathlib import Path

import pytest

from noesis.core import (
    load_claude_code_settings,
    write_env_file,
)

pytestmark = pytest.mark.unit


def test_settings_file_follows_claude_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom")

    assert load_claude_code_settings().settings_file == Path("/custom/settings.json")


@pytest.mark.parametrize("value", [None, ""])
def test_the_default_is_the_home_claude_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    if value is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", value)

    assert load_claude_code_settings().settings_file == tmp_path / ".claude/settings.json"


def test_write_env_file_sets_the_vault_line(tmp_path: Path) -> None:
    target: Path = tmp_path / "deep" / ".env"

    write_env_file(target, vault_dir=Path("/my/vault"))

    lines: list[str] = target.read_text(encoding="utf-8").splitlines()
    assert "NOESIS_VAULT_DIR=/my/vault" in lines


def test_write_env_file_without_a_vault_keeps_the_template(tmp_path: Path) -> None:
    target: Path = tmp_path / ".env"

    write_env_file(target)

    assert "NOESIS_VAULT_DIR" in target.read_text(encoding="utf-8")
