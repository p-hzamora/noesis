"""A session id handed over as a value (the `NOESIS_SESSION_ID` variable)."""

from .ambient_session_source import AmbientSessionSource


class StaticSessionIdentitySourceAdapter(AmbientSessionSource):
    """Returns the value it was built with; the composition root reads it via `core.env`."""

    def __init__(self, value: str | None) -> None:
        self._value: str | None = value

    def read(self) -> str | None:
        """The value, or None when blank."""
        return self._value.strip() or None if self._value else None
