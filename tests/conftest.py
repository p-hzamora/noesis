"""Fixtures shared by every test: isolation from the real user configuration."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG and Claude Code folders at `tmp_path` and drop every NOESIS_* variable, for every test.

    Returns:
        The fake home folder used for configuration and state.
    """
    home: Path = tmp_path / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    for name in [name for name in os.environ if name.startswith("NOESIS_")]:
        monkeypatch.delenv(name)
    return home
