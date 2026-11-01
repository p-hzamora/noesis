"""Append-only record of what capture did in a session."""

import abc

from noesis.bounded_context.capture.application.dtos import CaptureRunDto
from noesis.bounded_context.capture.domain.value_objects import SessionId


class ICaptureJournal(abc.ABC):
    """Per-session journal; sessions never share one."""

    @abc.abstractmethod
    async def append(self, session_id: SessionId, entry: CaptureRunDto) -> None:
        """Add an entry."""
        ...

    @abc.abstractmethod
    async def read(self, session_id: SessionId) -> list[CaptureRunDto]:
        """Every entry, oldest first, with curation results attached when available."""
        ...
