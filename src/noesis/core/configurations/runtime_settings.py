"""Settings for noesis itself: where its state lives and how much it logs."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings
from .paths import default_state_dir


class LogLevelEnum(StrEnum):
    """Accepted log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class RuntimeSettings(AppBaseSettings):
    """Process-wide settings.

    Attributes:
        state_dir: Folder for per-session capture state and logs (`NOESIS_STATE_DIR`).
        log_level: Minimum level noesis logs (`NOESIS_LOG_LEVEL`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    state_dir: Path = Field(default_factory=default_state_dir)
    log_level: LogLevelEnum = LogLevelEnum.INFO

    @field_validator("state_dir", mode="after")
    @classmethod
    def _expand_state_dir(cls, value: Path) -> Path:
        return value.expanduser()
