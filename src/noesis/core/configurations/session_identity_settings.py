"""Session ids that agents put in the environment of the commands they run."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class SessionIdentitySettings(AppBaseSettings):
    """Ambient session identity, read from the process environment only.

    The variables belong to the harnesses (or to the user), not to a noesis `.env` file.
    Empty values count as unset.

    Attributes:
        noesis_session_id: Session id the user exports for harnesses noesis does not know
            (`NOESIS_SESSION_ID`).
        codex_thread_id: Codex's stable thread id (`CODEX_THREAD_ID`).
        codex_session_id: Codex's session id, equal to the thread id (`CODEX_SESSION_ID`).
    """

    model_config = SettingsConfigDict(env_ignore_empty=True)

    noesis_session_id: str | None = Field(default=None, validation_alias="NOESIS_SESSION_ID")
    codex_thread_id: str | None = Field(default=None, validation_alias="CODEX_THREAD_ID")
    codex_session_id: str | None = Field(default=None, validation_alias="CODEX_SESSION_ID")
