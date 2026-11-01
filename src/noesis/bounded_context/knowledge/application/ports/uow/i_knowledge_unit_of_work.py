"""Unit of Work for note changes: all notes of one curation are written, or none."""

import abc

from noesis.bounded_context.knowledge.domain.repositories import INoteRepository
from noesis.shared_kernel.application.ports.uow import IUnitOfWork


class IKnowledgeUnitOfWork(IUnitOfWork["IKnowledgeUnitOfWork"]):
    """Exposes the note repository whose staged changes `commit` makes durable."""

    @property
    @abc.abstractmethod
    def notes(self) -> INoteRepository:
        """The note repository of this unit of work."""
        ...
