"""The session id Codex exposes to the commands it runs."""

from .ambient_session_source import AmbientSessionSource


class CodexSessionIdentitySourceAdapter(AmbientSessionSource):
    """`CODEX_THREAD_ID`, then `CODEX_SESSION_ID`.

    Codex sets both to the same UUID, and the value stays the same after `codex resume`
    (verified with `codex exec` before and after a resume). `CODEX_TOOL_CALL_ID` changes on
    every call and must never be used. The composition root reads the variables through
    `core.env` and injects the values; this adapter never touches the process environment.
    """

    def __init__(self, thread_id: str | None, session_id: str | None) -> None:
        self._candidates: tuple[str | None, ...] = (thread_id, session_id)

    def read(self) -> str | None:
        """The first non-blank id, or None outside Codex."""
        for candidate in self._candidates:
            if candidate and candidate.strip():
                return candidate.strip()
        return None
