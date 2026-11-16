"""`IKnowledgeUnitOfWork` as one explicit Neo4j transaction."""

from types import TracebackType
from typing import Self

from noesis.bounded_context.knowledge.application.ports.changes import IRecordChangeLog
from noesis.bounded_context.knowledge.application.ports.ledger import IIdempotencyLedger
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.domain.repositories import (
    IExperienceRepository,
    IKnowledgeRepository,
    IKnowledgeSpaceRepository,
    IProjectRepository,
    ISourceRepository,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .neo4j_experience_repository_adapter import Neo4jExperienceRepositoryAdapter
from .neo4j_idempotency_ledger_adapter import Neo4jIdempotencyLedgerAdapter
from .neo4j_knowledge_repository_adapter import Neo4jKnowledgeRepositoryAdapter
from .neo4j_knowledge_space_repository_adapter import Neo4jKnowledgeSpaceRepositoryAdapter
from .neo4j_project_repository_adapter import Neo4jProjectRepositoryAdapter
from .neo4j_record_change_log_adapter import Neo4jRecordChangeLogAdapter
from .neo4j_source_repository_adapter import Neo4jSourceRepositoryAdapter


class Neo4jKnowledgeUnitOfWorkAdapter(IKnowledgeUnitOfWork):
    """Begins a transaction on enter; `commit()` makes it durable; leaving without it rolls back.

    Every member shares the one transaction through `_current`, so a member added later
    (A-1) is one more property here and changes no handler.
    """

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client
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
        """Make every staged change durable."""
        await self._current().commit()

    async def rollback(self) -> None:
        """Discard every staged change; a no-op after commit."""
        if self._transaction is not None:
            await self._transaction.rollback()
