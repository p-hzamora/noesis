"""Where the payload of a failed apply is kept so that nothing the caller wrote is lost."""

import abc
from collections.abc import Sequence
from datetime import datetime

from noesis.bounded_context.notes.application.dtos import ApplyFailureRecordDto
from noesis.bounded_context.notes.domain.value_objects import NoteScope


class IApplyFailureLog(abc.ABC):
    """Durable record of apply payloads that were rejected or could not be stored."""

    @abc.abstractmethod
    async def record(
        self,
        *,
        raw_payload: str,
        scope: NoteScope,
        commits: tuple[str, ...],
        session: str | None,
        errors: Sequence[str],
        now: datetime,
    ) -> ApplyFailureRecordDto:
        """Keep the payload exactly as received, with why it failed.

        Raises:
            NoteStorageError: The record could not be written.
        """
        ...
