"""List notes of an area."""

from noesis.bounded_context.notes.application.dtos import NoteListDto
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import NoteArea, NoteOriginEnum
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListNotesQuery(FrozenObject):
    """List notes.

    Attributes:
        area: Restrict to one area; None lists the whole vault.
        origin: Restrict to manual or auto notes.
    """

    area: str | None = None
    origin: NoteOriginEnum | None = None


class ListNotesHandler(IHandler[ListNotesQuery, NoteListDto]):
    """Every note matching the filters, sorted by path."""

    def __init__(self, *, read_repository: INoteReadRepository) -> None:
        self._read_repository: INoteReadRepository = read_repository

    async def handle(self, action: ListNotesQuery) -> NoteListDto:
        """The matching notes."""
        area: NoteArea | None = NoteArea(value=action.area) if action.area else None
        return NoteListDto(
            notes=tuple(await self._read_repository.list_notes(area=area, origin=action.origin))
        )
