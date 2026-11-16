"""Settings for the LLM curator that decides what is worth keeping."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class CuratorRelatedLookupEnum(StrEnum):
    """Whether curated ingestion looks up related records before judging.

    REQUIRED: the lookup must answer, else the brief is parked (fail closed).
    OFF: no lookup; the curator gets no related records.
    """

    REQUIRED = "required"
    OFF = "off"


class CuratorSettings(AppBaseSettings):
    """Curator run settings.

    Attributes:
        claude_bin: The `claude` executable (`NOESIS_CURATOR_CLAUDE_BIN`).
        model: Model alias or id; empty uses the Claude Code default (`NOESIS_CURATOR_MODEL`).
        max_budget_usd: Spend cap for one run (`NOESIS_CURATOR_MAX_BUDGET_USD`).
        timeout_seconds: Time limit for one run (`NOESIS_CURATOR_TIMEOUT_SECONDS`).
        retry_seconds: Pause before the single automatic retry (`NOESIS_CURATOR_RETRY_SECONDS`).
        related_lookup: `required` (default) or `off`: whether curated ingestion looks up
            related records first (`NOESIS_CURATOR_RELATED_LOOKUP`); any other value is invalid.
        system_prompt_file: Your own system prompt instead of the packaged one
            (`NOESIS_CURATOR_SYSTEM_PROMPT_FILE`); unset uses the packaged prompt.
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_CURATOR_")

    claude_bin: str = "claude"
    model: str = ""
    max_budget_usd: float = Field(default=0.5, gt=0)
    timeout_seconds: float = Field(default=300.0, gt=0)
    retry_seconds: float = Field(default=30.0, ge=0)
    related_lookup: CuratorRelatedLookupEnum = CuratorRelatedLookupEnum.REQUIRED
    system_prompt_file: Path | None = None
