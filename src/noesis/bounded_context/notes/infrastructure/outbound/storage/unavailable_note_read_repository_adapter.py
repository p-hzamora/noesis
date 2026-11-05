"""`INoteReadRepository` for a setup with no local files: every call fails with a given error."""

from collections.abc import Callable

from noesis.bounded_context.notes.application.dtos import NoteSearchResultDto, NoteSummaryDto
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import NoteArea, NoteOriginEnum


class UnavailableNoteReadRepositoryAdapter(INoteReadRepository):
    """Listing for a vault-less setup: `notes list` needs files, so it fails when asked."""

    def __init__(self, error: Callable[[], Exception]) -> None:
        self._error = error

    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> NoteSearchResultDto:
        raise self._error()

    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        raise self._error()
