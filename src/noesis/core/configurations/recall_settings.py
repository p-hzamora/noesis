"""Settings for the agent that turns recalled notes into a task briefing."""

from enum import StrEnum

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class RecallRuntimeEnum(StrEnum):
    """The program that runs the recall agent; it is not the model it asks for."""

    CLAUDE_CLI = "claude-cli"


class RecallSettings(AppBaseSettings):
    """Recall agent run settings.

    Attributes:
        runtime: Program that runs the agent (`NOESIS_RECALL_RUNTIME`). Only `claude-cli`
            (headless Claude Code) exists today.
        model: Model name handed to the runtime verbatim (`NOESIS_RECALL_MODEL`); empty uses
            the runtime's default. noesis does not interpret it, so any name the runtime
            accepts works.
        effort: Reasoning effort handed to the runtime verbatim (`NOESIS_RECALL_EFFORT`);
            empty uses the runtime's default.
        claude_bin: The `claude` executable for the `claude-cli` runtime
            (`NOESIS_RECALL_CLAUDE_BIN`).
        max_budget_usd: Spend cap for one briefing (`NOESIS_RECALL_MAX_BUDGET_USD`).
        timeout_seconds: Time limit for one briefing (`NOESIS_RECALL_TIMEOUT_SECONDS`).
        max_input_chars: Most note text sent to the agent, shared among the notes read
            (`NOESIS_RECALL_MAX_INPUT_CHARS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_RECALL_")

    runtime: RecallRuntimeEnum = RecallRuntimeEnum.CLAUDE_CLI
    model: str = ""
    effort: str = ""
    claude_bin: str = "claude"
    max_budget_usd: float = Field(default=0.25, gt=0)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_input_chars: int = Field(default=60_000, ge=2_000)
