"""Builds the Knowledge context's Neo4j adapters around one shared client."""

from collections.abc import Sequence
from dataclasses import dataclass

from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.infrastructure.outbound.ids import (
    UlidRecordIdGeneratorAdapter,
)
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .neo4j_knowledge_unit_of_work_adapter import Neo4jKnowledgeUnitOfWorkAdapter
from .neo4j_record_read_repository_adapter import Neo4jRecordReadRepositoryAdapter
from .neo4j_store_schema_adapter import CORE_SCHEMA_STEP, Neo4jSchemaStep, Neo4jStoreSchemaAdapter


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgePersistence:
    """Everything the Knowledge handlers take from the store.

    Attributes:
        uow_factory: Opens a new unit of work (one transaction) per call.
        read_repository: The record read side.
        schema: Registered schema steps (`core` first, then `extra_steps`).
        ids: ULID generator.
    """

    uow_factory: KnowledgeUnitOfWorkFactory
    read_repository: IRecordReadRepository
    schema: IStoreSchema
    ids: IRecordIdGenerator


def build_knowledge_persistence(
    client: Neo4jClient, *, clock: IClock, extra_steps: Sequence[Neo4jSchemaStep] = ()
) -> KnowledgePersistence:
    """Wire the Neo4j adapters; opens no connection (the client connects on first use).

    Args:
        client: The invocation's shared client; the caller closes it when the command ends.
        clock: Clock stamping new ULIDs.
        extra_steps: Schema steps other modules register after `core` (A-3).

    Raises:
        InvalidConfigurationError: Two schema steps share a name.
    """

    def new_unit_of_work() -> IKnowledgeUnitOfWork:
        return Neo4jKnowledgeUnitOfWorkAdapter(client)

    return KnowledgePersistence(
        uow_factory=new_unit_of_work,
        read_repository=Neo4jRecordReadRepositoryAdapter(client),
        schema=Neo4jStoreSchemaAdapter(client, (CORE_SCHEMA_STEP, *extra_steps)),
        ids=UlidRecordIdGeneratorAdapter(clock),
    )
