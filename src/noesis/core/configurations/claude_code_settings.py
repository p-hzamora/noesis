"""Where Claude Code keeps its user settings (the file noesis registers its hooks in)."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings

SETTINGS_FILE_NAME: str = "settings.json"


class ClaudeCodeSettings(AppBaseSettings):
    """Claude Code's configuration folder, as the Claude Code CLI itself resolves it.

    Read from the process environment only (a noesis `.env` is not consulted): the variable
    belongs to Claude Code, not to noesis.

    Attributes:
        config_dir: Folder with Claude Code's user configuration (`CLAUDE_CONFIG_DIR`,
            default `~/.claude`; an empty value means the default).
    """

    model_config = SettingsConfigDict(env_ignore_empty=True)

    config_dir: Path = Field(default=Path("~/.claude"), validation_alias="CLAUDE_CONFIG_DIR")

    @field_validator("config_dir", mode="after")
    @classmethod
    def _expand_config_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def settings_file(self) -> Path:
        """`<config_dir>/settings.json`."""
        return self.config_dir / SETTINGS_FILE_NAME
