"""Where Codex keeps its home folder (the plugins noesis lists in `catalog check`)."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class CodexSettings(AppBaseSettings):
    """Codex's home folder, as the Codex CLI itself resolves it.

    Read from the process environment only (a noesis `.env` is not consulted): the variable
    belongs to Codex, not to noesis. The field is not called `home`: settings also read a field's
    own name from the environment, and `HOME` would then set it.

    Attributes:
        codex_home: Folder with Codex's configuration and plugin cache (`CODEX_HOME`, default
            `~/.codex`; an empty value means the default).
    """

    model_config = SettingsConfigDict(env_ignore_empty=True)

    codex_home: Path = Field(default=Path("~/.codex"), validation_alias="CODEX_HOME")

    @field_validator("codex_home", mode="after")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()
