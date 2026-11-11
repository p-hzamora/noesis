"""List notes of a scope."""

from noesis.bounded_context.notes.application.dtos import NoteListDto
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import NoteOriginEnum, NoteScope
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListNotesQuery(FrozenObject):
    """List notes.

    Attributes:
        scope: Restrict to one scope (`repo:<name>`, `topic:<name>`); None lists every note.
        origin: Restrict to manual or auto notes.
    """

    scope: str | None = None
    origin: NoteOriginEnum | None = None


class ListNotesHandler(IHandler[ListNotesQuery, NoteListDto]):
    """Every note matching the filters, sorted by path."""

    def __init__(self, *, read_repository: INoteReadRepository) -> None:
        self._read_repository: INoteReadRepository = read_repository

    async def handle(self, action: ListNotesQuery) -> NoteListDto:
        """The matching notes."""
        scope: NoteScope | None = NoteScope.parse(action.scope) if action.scope else None
        return NoteListDto(
            notes=tuple(await self._read_repository.list_notes(scope=scope, origin=action.origin))
        )
