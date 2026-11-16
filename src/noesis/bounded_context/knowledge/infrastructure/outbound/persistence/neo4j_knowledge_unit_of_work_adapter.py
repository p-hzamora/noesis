"""`IKnowledgeUnitOfWork` as one explicit Neo4j transaction."""

from types import TracebackType
from typing import Self

from noesis.bounded_context.knowledge.application.ports.changes import IRecordChangeLog
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationGuardLookup,
)
from noesis.bounded_context.knowledge.application.ports.ledger import IIdempotencyLedger
from noesis.bounded_context.knowledge.application.ports.references import IRecordReferenceLookup
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
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
from noesis.exceptions import GraphStoreConstraintViolatedError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .neo4j_assertion_repository_adapter import Neo4jAssertionRepositoryAdapter
from .neo4j_catalog_entry_repository_adapter import Neo4jCatalogEntryRepositoryAdapter
from .neo4j_consolidation_guard_lookup_adapter import Neo4jConsolidationGuardLookupAdapter
from .neo4j_consolidation_repository_adapter import Neo4jConsolidationRepositoryAdapter
from .neo4j_experience_repository_adapter import Neo4jExperienceRepositoryAdapter
from .neo4j_idempotency_ledger_adapter import Neo4jIdempotencyLedgerAdapter
from .neo4j_knowledge_repository_adapter import Neo4jKnowledgeRepositoryAdapter
from .neo4j_knowledge_space_repository_adapter import Neo4jKnowledgeSpaceRepositoryAdapter
from .neo4j_link_set_repository_adapter import Neo4jLinkSetRepositoryAdapter
from .neo4j_project_repository_adapter import Neo4jProjectRepositoryAdapter
from .neo4j_record_change_log_adapter import Neo4jRecordChangeLogAdapter
from .neo4j_record_reference_lookup_adapter import Neo4jRecordReferenceLookupAdapter
from .neo4j_review_write_support import LIVE_KEY_PROPERTY, status_conflict
from .neo4j_source_repository_adapter import Neo4jSourceRepositoryAdapter


class Neo4jKnowledgeUnitOfWorkAdapter(IKnowledgeUnitOfWork):
    """Begins a transaction on enter; `commit()` makes it durable; leaving without it rolls back.

    Every member shares the one transaction through `_current`, so a member added later
    (A-1) is one more property here and changes no handler.
    """

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client
        self._link_sets = Neo4jLinkSetRepositoryAdapter(self._current)
        self._transaction: Neo4jTransaction | None = None
        self._spaces: Neo4jKnowledgeSpaceRepositoryAdapter = Neo4jKnowledgeSpaceRepositoryAdapter(
            self._current
        )
        self._projects: Neo4jProjectRepositoryAdapter = Neo4jProjectRepositoryAdapter(self._current)
        self._sources: Neo4jSourceRepositoryAdapter = Neo4jSourceRepositoryAdapter(self._current)
        self._knowledge: Neo4jKnowledgeRepositoryAdapter = Neo4jKnowledgeRepositoryAdapter(
            self._current, client
        )
        self._experiences: Neo4jExperienceRepositoryAdapter = Neo4jExperienceRepositoryAdapter(
            self._current
        )
        self._ledger: Neo4jIdempotencyLedgerAdapter = Neo4jIdempotencyLedgerAdapter(self._current)
        self._changes: Neo4jRecordChangeLogAdapter = Neo4jRecordChangeLogAdapter(self._current)
        self._assertions: Neo4jAssertionRepositoryAdapter = Neo4jAssertionRepositoryAdapter(
            self._current, client
        )
        self._record_references: Neo4jRecordReferenceLookupAdapter = (
            Neo4jRecordReferenceLookupAdapter(self._current)
        )
        self._catalog_entries: Neo4jCatalogEntryRepositoryAdapter = (
            Neo4jCatalogEntryRepositoryAdapter(self._current, client)
        )
        self._consolidations: Neo4jConsolidationRepositoryAdapter = (
            Neo4jConsolidationRepositoryAdapter(self._current, client)
        )
        self._consolidation_guard: Neo4jConsolidationGuardLookupAdapter = (
            Neo4jConsolidationGuardLookupAdapter(self._current)
        )

    def _current(self) -> Neo4jTransaction:
        """The open transaction.

        Raises:
            RuntimeError: Used outside `async with` or after commit (a programming error).
        """
        if self._transaction is None or not self._transaction.is_open:
            raise RuntimeError("The knowledge unit of work is used outside `async with`.")
        return self._transaction

    @property
    def spaces(self) -> IKnowledgeSpaceRepository:
        """Knowledge spaces."""
        return self._spaces

    @property
    def projects(self) -> IProjectRepository:
        """Projects."""
        return self._projects

    @property
    def sources(self) -> ISourceRepository:
        """Sources."""
        return self._sources

    @property
    def knowledge(self) -> IKnowledgeRepository:
        """Knowledge records."""
        return self._knowledge

    @property
    def experiences(self) -> IExperienceRepository:
        """Experiences."""
        return self._experiences

    @property
    def ledger(self) -> IIdempotencyLedger:
        """The idempotency ledger."""
        return self._ledger

    @property
    def changes(self) -> IRecordChangeLog:
        """The change log."""
        return self._changes

    @property
    def assertions(self) -> IAssertionRepository:
        """Assertions."""
        return self._assertions

    @property
    def record_references(self) -> IRecordReferenceLookup:
        """Record reference lookup over the generic record label."""
        return self._record_references

    @property
    def catalog_entries(self) -> ICatalogEntryRepository:
        """Catalog entries."""
        return self._catalog_entries

    @property
    def link_sets(self) -> ILinkSetRepository:
        """Imported outgoing links."""
        return self._link_sets

    @property
    def consolidations(self) -> IConsolidationRepository:
        """Consolidations."""
        return self._consolidations

    @property
    def consolidation_guard(self) -> IConsolidationGuardLookup:
        """Open memberships, dismissed pairs and independent evidence."""
        return self._consolidation_guard

    async def __aenter__(self) -> Self:
        """Begin the transaction; an unreachable store fails here (INTEGRATION_103)."""
        self._transaction = await self._client.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed, and release the session."""
        await self.rollback()

    async def commit(self) -> None:
        """Make every staged change durable.

        Raises:
            StatusConflictError: A decision key clashed (reported at commit).
            DuplicateAssertionError: A live statement clashed (reported at commit).
        """
        try:
            await self._current().commit()
        except GraphStoreConstraintViolatedError as error:
            conflict = status_conflict(error)
            if conflict is not None:
                raise conflict from error
            if error.metadata.get("property") == LIVE_KEY_PROPERTY:
                raise await self._assertions.duplicate_error() from error
            raise

    async def rollback(self) -> None:
        """Discard every staged change; a no-op after commit."""
        if self._transaction is not None:
            await self._transaction.rollback()
