"""Wires the `remember` handler over one Neo4j client per invocation.

Remember reuses the capture and assertion handlers and asks Retrieval's shared search pipeline
for records like the new one through the kernel contract. Building the client opens no
connection, so `--help`, usage errors and a missing password never reach the store.
"""

from collections.abc import Awaitable, Callable

from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.remember_handler import (
    RememberHandler,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    KnowledgePersistence,
    build_knowledge_persistence,
)
from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge import (
    RelatedRecordFinderAdapter,
)
from noesis.core import Environment
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts.ports.knowledge import IRelatedRecordFinder
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .knowledge_handlers_builder import EXTRA_SCHEMA_STEPS
from .retrieval_handlers_builder import build_retrieval


def build_remember(
    client: Neo4jClient,
    environment: Environment,
    *,
    finder: IRelatedRecordFinder | None = None,
) -> RememberHandler:
    """Wire the handler over `client` (the caller closes it); opens no connection.

    Args:
        client: The invocation's Neo4j client.
        environment: Loaded settings.
        finder: Related-records lookup to use instead of Retrieval's (tests).
    """
    clock: IClock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    related: IRelatedRecordFinder = finder or RelatedRecordFinderAdapter(
        build_retrieval(client, environment).searcher
    )
    return RememberHandler(
        uow_factory=persistence.uow_factory,
        clock=clock,
        ids=persistence.ids,
        schema=persistence.schema,
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
        propose_assertion=ProposeAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        records=persistence.read_repository,
        catalog=persistence.catalog_read_repository,
        finder=related,
    )


async def with_remember[T](
    environment: Environment, use: Callable[[RememberHandler], Awaitable[T]]
) -> T:
    """Run `use` over the invocation's handler and close the client afterwards.

    Raises:
        InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set.
    """
    async with Neo4jClient(environment.knowledge.neo4j_connection()) as client:
        return await use(build_remember(client, environment))
