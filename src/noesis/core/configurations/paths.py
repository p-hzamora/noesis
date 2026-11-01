"""Default locations, following the XDG base directory convention."""

import os
from pathlib import Path

APP_DIR_NAME: str = "noesis"


def _xdg_dir(variable: str, fallback: str) -> Path:
    """`$variable` when set and absolute, else `~/<fallback>`."""
    value: str = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def default_env_file() -> Path:
    """`$XDG_CONFIG_HOME/noesis/.env` (normally `~/.config/noesis/.env`)."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME / ".env"


def default_state_dir() -> Path:
    """`$XDG_STATE_HOME/noesis` (normally `~/.local/state/noesis`)."""
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_DIR_NAME
