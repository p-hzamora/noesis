"""`INoteReadRepository` for a setup with no local files: every call fails with a given error."""

from collections.abc import Callable

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
)
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
)


class UnavailableNoteReadRepositoryAdapter(INoteReadRepository):
    """Vault-less setup: search, list and read fail when asked; lookups find nothing."""

    def __init__(self, error: Callable[[], Exception]) -> None:
        self._error = error

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        raise self._error()

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        raise self._error()

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """No files to look in, so nothing is known: curation proceeds without duplicates check."""
        return []

    async def find_by_id(
        self, note_id: NoteId, *, scope: NoteScope | None
    ) -> NoteSummaryDto | None:
        return None

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        raise self._error()
