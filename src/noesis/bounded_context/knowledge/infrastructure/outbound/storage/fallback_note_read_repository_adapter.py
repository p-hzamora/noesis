"""`INoteReadRepository` that degrades from a preferred repository to the filesystem."""

from collections.abc import Callable

from noesis.bounded_context.knowledge.application.dtos import NoteSummaryDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.knowledge.domain.value_objects import NoteArea, NoteOriginEnum
from noesis.exceptions import ObsidianMcpError


class FallbackNoteReadRepositoryAdapter(INoteReadRepository):
    """Searches with `preferred`; when it fails, searches with `fallback` instead.

    After the first failure the preferred repository is not tried again by this instance, so
    one process pays the unreachable-server timeout once, and `on_fallback` fires once.
    """

    def __init__(
        self,
        preferred: INoteReadRepository,
        fallback: INoteReadRepository,
        *,
        on_fallback: Callable[[ObsidianMcpError], None],
    ) -> None:
        self._preferred: INoteReadRepository = preferred
        self._fallback: INoteReadRepository = fallback
        self._on_fallback: Callable[[ObsidianMcpError], None] = on_fallback
        self._degraded: bool = False

    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> list[NoteSummaryDto]:
        """Preferred results, or the fallback's (and one notification) when it is unavailable."""
        if not self._degraded:
            try:
                return await self._preferred.search(text, area=area, limit=limit)
            except ObsidianMcpError as error:
                self._degraded = True
                self._on_fallback(error)
        return await self._fallback.search(text, area=area, limit=limit)

    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Always the fallback: listing never goes through Obsidian."""
        return await self._fallback.list_notes(area=area, origin=origin)
