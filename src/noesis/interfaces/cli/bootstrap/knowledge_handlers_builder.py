"""Wires the Knowledge handlers over one Neo4j client per invocation.

The client is built when a command starts and closed when it ends (`open_knowledge`). Building
it opens no connection: the driver is created on the first query, so `--help`, usage errors and
a missing password never reach this module or the store.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

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
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CORE_SCHEMA_STEP,
    KnowledgePersistence,
    Neo4jSchemaStep,
    build_knowledge_persistence,
)
from noesis.core import Environment
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

EXTRA_SCHEMA_STEPS: tuple[Neo4jSchemaStep, ...] = ()
"""Schema steps other modules register after `core` (A-3); later chunks append here."""


def registered_schema_step_names() -> tuple[str, ...]:
    """Names of every schema step `store init` applies, in order (no connection needed)."""
    return tuple(step.name for step in (CORE_SCHEMA_STEP, *EXTRA_SCHEMA_STEPS))


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeHandlers:
    """The record store actions of one invocation, wired.

    Attributes:
        capture_knowledge: Propose graph-owned knowledge.
        capture_experience: Record an experience.
        revise_knowledge: Append a revision to proposed knowledge.
        get_record: Read a record by id.
        initialise_store: Apply the schema steps and ensure the default space.
    """

    capture_knowledge: CaptureKnowledgeHandler
    capture_experience: CaptureExperienceHandler
    revise_knowledge: ReviseKnowledgeHandler
    get_record: GetRecordHandler
    initialise_store: InitialiseStoreHandler


def build_knowledge(client: Neo4jClient, environment: Environment) -> KnowledgeHandlers:
    """Wire the handlers over `client` (the caller closes it); opens no connection."""
    clock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    return KnowledgeHandlers(
        capture_knowledge=CaptureKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        capture_experience=CaptureExperienceHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        revise_knowledge=ReviseKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        get_record=GetRecordHandler(
            read_repository=persistence.read_repository, schema=persistence.schema
        ),
        initialise_store=InitialiseStoreHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
    )


@asynccontextmanager
async def open_knowledge(environment: Environment) -> AsyncIterator[KnowledgeHandlers]:
    """Handlers over a client that is closed when the block ends, however it ends.

    Raises:
        InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set.
    """
    connection = environment.knowledge.neo4j_connection()
    async with Neo4jClient(connection) as client:
        yield build_knowledge(client, environment)


async def with_knowledge[T](
    environment: Environment, use: Callable[[KnowledgeHandlers], Awaitable[T]]
) -> T:
    """Run `use` over the invocation's handlers and close the client afterwards."""
    async with open_knowledge(environment) as handlers:
        return await use(handlers)
