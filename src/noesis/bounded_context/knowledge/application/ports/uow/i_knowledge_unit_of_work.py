"""Unit of Work of the Knowledge context: one aggregate mutated per transaction."""

import abc

from noesis.bounded_context.knowledge.application.ports.ledger import IIdempotencyLedger
from noesis.bounded_context.knowledge.domain.repositories import (
    IExperienceRepository,
    IKnowledgeRepository,
    IKnowledgeSpaceRepository,
    IProjectRepository,
    ISourceRepository,
)
from noesis.shared_kernel.application.ports.uow import IUnitOfWork


class IKnowledgeUnitOfWork(IUnitOfWork["IKnowledgeUnitOfWork"]):
    """Exposes the repositories and the ledger of one transaction.

    Later chunks extend it with new members only (`changes`, `assertions`, `record_references`,
    `catalog_entries`, `link_sets`, `consolidations`, `consolidation_guard`); handlers receive a
    factory and use only the members they need, so adding one changes no existing handler.
    """

    @property
    @abc.abstractmethod
    def spaces(self) -> IKnowledgeSpaceRepository:
        """Knowledge spaces."""
        ...

    @property
    @abc.abstractmethod
    def projects(self) -> IProjectRepository:
        """Projects."""
        ...

    @property
    @abc.abstractmethod
    def sources(self) -> ISourceRepository:
        """Sources."""
        ...

    @property
    @abc.abstractmethod
    def knowledge(self) -> IKnowledgeRepository:
        """Knowledge records."""
        ...

    @property
    @abc.abstractmethod
    def experiences(self) -> IExperienceRepository:
        """Experiences."""
        ...

    @property
    @abc.abstractmethod
    def ledger(self) -> IIdempotencyLedger:
        """The idempotency ledger; its entry commits with the aggregate change."""
        ...
