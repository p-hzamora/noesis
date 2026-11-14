"""The Knowledge handlers wired to the real Neo4j adapters, and raw-graph inspection helpers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, LiteralString

from neo4j import Driver
from tests.support.knowledge_support import MutableClock
from tests.support.neo4j_container import admin_driver

from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordHandler,
)
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    KnowledgePersistence,
    Neo4jSchemaStep,
    build_knowledge_persistence,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings


@dataclass(slots=True)
class Neo4jKnowledgeEnv:
    """One invocation's client, its persistence and the handlers over it."""

    client: Neo4jClient
    persistence: KnowledgePersistence
    clock: MutableClock

    def uow(self) -> IKnowledgeUnitOfWork:
        """A fresh unit of work (one transaction)."""
        return self.persistence.uow_factory()

    def _deps(self) -> dict[str, Any]:
        return {
            "uow_factory": self.persistence.uow_factory,
            "clock": self.clock,
            "ids": self.persistence.ids,
            "schema": self.persistence.schema,
        }

    @property
    def initialise_store(self) -> InitialiseStoreHandler:
        """`store init` over the real store."""
        return InitialiseStoreHandler(**self._deps())

    @property
    def capture_knowledge(self) -> CaptureKnowledgeHandler:
        """Capture knowledge over the real store."""
        return CaptureKnowledgeHandler(**self._deps())

    @property
    def capture_experience(self) -> CaptureExperienceHandler:
        """Capture an experience over the real store."""
        return CaptureExperienceHandler(**self._deps())

    @property
    def revise_knowledge(self) -> ReviseKnowledgeHandler:
        """Revise over the real store."""
        return ReviseKnowledgeHandler(**self._deps())

    @property
    def get_record(self) -> GetRecordHandler:
        """`record get` over the real store."""
        return GetRecordHandler(
            read_repository=self.persistence.read_repository, schema=self.persistence.schema
        )

    @property
    def references(self) -> RecordReferenceResolver:
        """The project and source ensures, as the capture handlers run them."""
        return RecordReferenceResolver(
            uow_factory=self.persistence.uow_factory, clock=self.clock, ids=self.persistence.ids
        )


def make_neo4j_env(
    settings: Neo4jConnectionSettings, *, extra_steps: Sequence[Neo4jSchemaStep] = ()
) -> Neo4jKnowledgeEnv:
    """A fresh client and handlers; close `env.client` when done."""
    client = Neo4jClient(settings)
    clock = MutableClock()
    return Neo4jKnowledgeEnv(
        client=client,
        persistence=build_knowledge_persistence(client, clock=clock, extra_steps=extra_steps),
        clock=clock,
    )


def query(
    settings: Neo4jConnectionSettings, cypher: LiteralString, **parameters: Any
) -> list[dict[str, Any]]:
    """Run read-only Cypher outside the code under test."""
    driver: Driver
    with admin_driver(settings) as driver:
        records, _, _ = driver.execute_query(cypher, parameters, database_=settings.database)
    return [record.data() for record in records]


def node_counts(settings: Neo4jConnectionSettings) -> dict[str, int]:
    """How many nodes carry each label, to prove a command wrote nothing."""
    rows: list[dict[str, Any]] = query(
        settings, "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS total"
    )
    return {row["label"]: row["total"] for row in rows}
