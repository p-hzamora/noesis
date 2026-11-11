"""Read repository for notes: search, listing and lookup, returning DTOs."""

import abc

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
)
from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
)


class INoteReadRepository(abc.ABC):
    """Queries over stored notes. A note is a file with a `noesis:` block, wherever it sits."""

    @abc.abstractmethod
    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Notes matching `text`, best match first, tagged with the backend that answered.

        Args:
            text: Free-text query.
            scope: Restrict to one scope; None searches every note.
            limit: Maximum number of results.
        """
        ...

    @abc.abstractmethod
    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every note, optionally restricted to a scope and an origin, sorted by path."""
        ...

    @abc.abstractmethod
    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """Every note of `scope` and `kind`, sorted by path (curation looks here before it creates)."""
        ...

    @abc.abstractmethod
    async def find_by_id(self, note_id: NoteId) -> NoteSummaryDto | None:
        """The note with this id wherever its file is, or None."""
        ...

    @abc.abstractmethod
    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """One note in full, read-only.

        Args:
            path: Source-relative path of a Markdown note, as `search` returned it.
            scope: When given, the note must belong to this scope.

        Raises:
            NoteStorageError: The path is outside the source, the note is not a noesis note of
                `scope`, or it cannot be read.
        """
        ...
