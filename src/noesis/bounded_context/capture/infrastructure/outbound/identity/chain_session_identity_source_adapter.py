"""`ISessionIdentitySource` that asks harness sources in order."""

import uuid
from collections.abc import Sequence

from noesis.bounded_context.capture.application.ports.identity import ISessionIdentitySource

from .ambient_session_source import AmbientSessionSource


class ChainSessionIdentitySourceAdapter(ISessionIdentitySource):
    """The first source that knows an id wins; with none, `fresh` is a random uuid4."""

    def __init__(self, sources: Sequence[AmbientSessionSource]) -> None:
        self._sources: tuple[AmbientSessionSource, ...] = tuple(sources)

    def ambient(self) -> str | None:
        """The first id any source sees."""
        for source in self._sources:
            found: str | None = source.read()
            if found:
                return found
        return None

    def fresh(self) -> str:
        """A new random id."""
        return uuid.uuid4().hex
