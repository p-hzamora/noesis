"""Session ids and harness markers that agents put in the environment of the commands they run.

This module is the one list of harness environment variables; Capture's session chain and the
CLI's actor resolution both read them through `Environment.identity`.
"""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class SessionIdentitySettings(AppBaseSettings):
    """Ambient session identity, read from the process environment only.

    The variables belong to the harnesses (or to the user), not to a noesis `.env` file.
    Empty values count as unset. Any non-empty value of a variable below marks the process as
    running inside an agent harness.

    Attributes:
        noesis_session_id: Session id the user exports for harnesses noesis does not know
            (`NOESIS_SESSION_ID`).
        codex_thread_id: Codex's stable thread id (`CODEX_THREAD_ID`).
        codex_session_id: Codex's session id, equal to the thread id (`CODEX_SESSION_ID`).
        claudecode: Set to `1` by Claude Code in every shell it spawns (`CLAUDECODE`).
        claude_code_session_id: Claude Code's session id in the shells it spawns
            (`CLAUDE_CODE_SESSION_ID`).
        ai_agent: Agent identification some harnesses set, e.g. `claude-code_2-1-325_agent`
            (`AI_AGENT`).
    """

    model_config = SettingsConfigDict(env_ignore_empty=True)

    noesis_session_id: str | None = Field(default=None, validation_alias="NOESIS_SESSION_ID")
    codex_thread_id: str | None = Field(default=None, validation_alias="CODEX_THREAD_ID")
    codex_session_id: str | None = Field(default=None, validation_alias="CODEX_SESSION_ID")
    claudecode: str | None = Field(default=None, validation_alias="CLAUDECODE")
    claude_code_session_id: str | None = Field(
        default=None, validation_alias="CLAUDE_CODE_SESSION_ID"
    )
    ai_agent: str | None = Field(default=None, validation_alias="AI_AGENT")
