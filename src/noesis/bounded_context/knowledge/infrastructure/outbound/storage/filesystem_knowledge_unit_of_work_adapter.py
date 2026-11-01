"""Unit of Work over the filesystem note repository: commit writes, anything else discards."""

from types import TracebackType
from typing import Self

from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.domain.repositories import INoteRepository
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.filesystem_note_repository_adapter import (
    FilesystemNoteRepositoryAdapter,
)


class FilesystemKnowledgeUnitOfWorkAdapter(IKnowledgeUnitOfWork):
    """Writes the staged notes on `commit`; leaving without a commit writes nothing."""

    def __init__(self, repository: FilesystemNoteRepositoryAdapter) -> None:
        self._repository: FilesystemNoteRepositoryAdapter = repository

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
        self._repository.flush()

    async def rollback(self) -> None:
        """Drop every staged note."""
        self._repository.discard()
