"""Search notes by free text."""

from pydantic import Field

from noesis.bounded_context.notes.application.dtos import NoteSearchResultDto
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import NoteScope
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class SearchNotesQuery(FrozenObject):
    """Find notes about `text`.

    Attributes:
        text: Free-text query.
        scope: Restrict to one scope (e.g. `repo:noesis`); None searches everything.
        limit: Maximum number of results.
    """

    text: str = Field(min_length=1)
    scope: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class SearchNotesHandler(IHandler[SearchNotesQuery, NoteSearchResultDto]):
    """Free-text search over the vault."""

    def __init__(self, *, read_repository: INoteReadRepository) -> None:
        self._read_repository: INoteReadRepository = read_repository

    async def handle(self, action: SearchNotesQuery) -> NoteSearchResultDto:
        """Notes matching the query, best match first, and the backend that found them."""
        scope: NoteScope | None = NoteScope.parse(action.scope) if action.scope else None
        return await self._read_repository.search(action.text, scope=scope, limit=action.limit)
