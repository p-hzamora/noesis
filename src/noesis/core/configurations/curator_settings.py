"""Settings for the LLM curator that decides what is worth keeping."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from noesis.core.configurations.base_settings import AppBaseSettings


class CuratorSettings(AppBaseSettings):
    """Curator run settings.

    Attributes:
        claude_bin: The `claude` executable (`NOESIS_CURATOR_CLAUDE_BIN`).
        model: Model alias or id; empty uses the Claude Code default (`NOESIS_CURATOR_MODEL`).
        max_budget_usd: Spend cap for one run (`NOESIS_CURATOR_MAX_BUDGET_USD`).
        timeout_seconds: Time limit for one run (`NOESIS_CURATOR_TIMEOUT_SECONDS`).
        retry_seconds: Pause before the single automatic retry (`NOESIS_CURATOR_RETRY_SECONDS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_CURATOR_")

    claude_bin: str = "claude"
    model: str = ""
    max_budget_usd: float = Field(default=0.5, gt=0)
    timeout_seconds: float = Field(default=300.0, gt=0)
    retry_seconds: float = Field(default=30.0, ge=0)
