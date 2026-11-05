"""Read repository for notes: search and listing, returning DTOs."""

import abc

from noesis.bounded_context.notes.application.dtos import NoteSearchResultDto, NoteSummaryDto
from noesis.bounded_context.notes.domain.value_objects import NoteArea, NoteOriginEnum


class INoteReadRepository(abc.ABC):
    """Queries over stored notes."""

    @abc.abstractmethod
    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> NoteSearchResultDto:
        """Notes matching `text`, best match first, tagged with the backend that answered.

        Args:
            text: Free-text query.
            area: Restrict to one area; None searches the whole vault.
            limit: Maximum number of results.
        """
        ...

    @abc.abstractmethod
    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every note, optionally restricted to an area and an origin, sorted by path."""
        ...
