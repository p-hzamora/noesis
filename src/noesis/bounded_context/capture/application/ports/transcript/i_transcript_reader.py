"""Reads an agent's session transcript."""

import abc
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import TranscriptSnapshotDto


class ITranscriptReader(abc.ABC):
    """Turns an agent transcript into what Capture needs to know."""

    @abc.abstractmethod
    async def read(self, path: Path | None, *, since_offset: int) -> TranscriptSnapshotDto | None:
        """Snapshot of the transcript, with work and excerpt counted from `since_offset`.

        Args:
            path: Transcript file; None when the agent gave none.
            since_offset: Cursor of the last hand-over; past the end means the file was rewritten.

        Returns:
            The snapshot, or None when the transcript cannot be read.
        """
        ...
