"""Unit of Work of the Knowledge context: one aggregate mutated per transaction."""

import abc

from noesis.bounded_context.knowledge.application.ports.changes import IRecordChangeLog
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationGuardLookup,
)
from noesis.bounded_context.knowledge.application.ports.ledger import IIdempotencyLedger
from noesis.bounded_context.knowledge.application.ports.references import IRecordReferenceLookup
from noesis.bounded_context.knowledge.domain.repositories import (
    IAssertionRepository,
    ICatalogEntryRepository,
    IConsolidationRepository,
    IExperienceRepository,
    IKnowledgeRepository,
    IKnowledgeSpaceRepository,
    IProjectRepository,
    ISourceRepository,
)
from noesis.bounded_context.knowledge.domain.repositories.i_link_set_repository import (
    ILinkSetRepository,
)
from noesis.shared_kernel.application.ports.uow import IUnitOfWork


class IKnowledgeUnitOfWork(IUnitOfWork["IKnowledgeUnitOfWork"]):
    """Exposes the repositories and the ledger of one transaction.

    Later chunks extend it with new members only (`assertions`, `record_references`,
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

    @property
    @abc.abstractmethod
    def changes(self) -> IRecordChangeLog:
        """The change log; its entries commit with the aggregate change."""
        ...

    @property
    @abc.abstractmethod
    def assertions(self) -> IAssertionRepository:
        """Assertions."""
        ...

    @property
    @abc.abstractmethod
    def record_references(self) -> IRecordReferenceLookup:
        """Write-side guard read over every record type."""
        ...

    @property
    @abc.abstractmethod
    def catalog_entries(self) -> ICatalogEntryRepository:
        """Catalog entries."""
        ...

    @property
    @abc.abstractmethod
    def link_sets(self) -> ILinkSetRepository:
        """Imported outgoing links; endpoint locks change no record properties."""
        ...

    @property
    @abc.abstractmethod
    def consolidations(self) -> IConsolidationRepository:
        """Consolidations, the bookkeeping of overlapping Knowledge."""
        ...

    @property
    @abc.abstractmethod
    def consolidation_guard(self) -> IConsolidationGuardLookup:
        """Open memberships, `distinct` dismissals and independent evidence."""
        ...
