"""`INoteReadRepository` that degrades from a preferred repository to the filesystem."""

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
from noesis.exceptions import ObsidianMcpError


class FallbackNoteReadRepositoryAdapter(INoteReadRepository):
    """Searches with `preferred`; when it fails, searches with `fallback` instead.

    `fails_with` names the errors that mean "preferred is unavailable" (Obsidian's MCP server
    unreachable by default; a vectra collection that cannot answer for the vectra backend).

    After the first failure the preferred repository is not tried again by this instance, so
    one process pays the unreachable-server timeout once, and `on_fallback` fires once.
    """

    def __init__(
        self,
        preferred: INoteReadRepository,
        fallback: INoteReadRepository,
        *,
        on_fallback: Callable[[Exception], None],
        fails_with: tuple[type[Exception], ...] = (ObsidianMcpError,),
    ) -> None:
        self._preferred: INoteReadRepository = preferred
        self._fallback: INoteReadRepository = fallback
        self._on_fallback: Callable[[Exception], None] = on_fallback
        self._fails_with: tuple[type[Exception], ...] = fails_with
        self._degraded: bool = False

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Preferred results, or the fallback's (and one notification) when it is unavailable.

        The result's `backend` names whichever repository really answered.
        """
        if not self._degraded:
            try:
                return await self._preferred.search(text, scope=scope, limit=limit)
            except self._fails_with as error:
                self._degraded = True
                self._on_fallback(error)
        return await self._fallback.search(text, scope=scope, limit=limit)

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Always the fallback: listing never goes through Obsidian."""
        return await self._fallback.list_notes(scope=scope, origin=origin)

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """Always the fallback: lookups never go through Obsidian."""
        return await self._fallback.find_active(scope, kind)

    async def find_by_id(
        self, note_id: NoteId, *, scope: NoteScope | None
    ) -> NoteSummaryDto | None:
        """Always the fallback: lookups never go through Obsidian."""
        return await self._fallback.find_by_id(note_id, scope=scope)

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """The preferred repository's note, or the fallback's when it is unavailable."""
        if not self._degraded:
            try:
                return await self._preferred.read_note(path, scope=scope)
            except self._fails_with as error:
                self._degraded = True
                self._on_fallback(error)
        return await self._fallback.read_note(path, scope=scope)
