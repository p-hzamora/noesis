"""Unit of Work over the vectra note repository: commit writes and indexes, anything else discards."""

from types import TracebackType
from typing import Self

from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.domain.repositories import INoteRepository

from .vectra_note_repository_adapter import VectraNoteRepositoryAdapter


class VectraNotesUnitOfWorkAdapter(INotesUnitOfWork):
    """Writes and indexes the staged notes on `commit`; leaving without a commit writes nothing."""

    def __init__(self, repository: VectraNoteRepositoryAdapter) -> None:
        self._repository: VectraNoteRepositoryAdapter = repository

    @property
    def notes(self) -> INoteRepository:
        """The repository staging this unit's notes."""
        return self._repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()  # no-op after a commit: the stage is already empty

    async def commit(self) -> None:
        """Write every staged note."""
        await self._repository.flush()

    async def rollback(self) -> None:
        """Drop every staged note."""
        self._repository.discard()
