"""Wires the consolidation handlers over one Neo4j client per invocation.

Scan asks Retrieval's shared search pipeline for similar records through the kernel contract;
every other command needs only Knowledge. Building the client opens no connection, so `--help`,
usage errors and a missing password never reach the store.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from noesis.bounded_context.knowledge.application.handlers.commands.accept_consolidation_handler import (
    AcceptConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_consolidation_handler import (
    ProposeConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.reject_consolidation_handler import (
    RejectConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.scan_consolidation_candidates_handler import (
    ScanConsolidationCandidatesHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.show_consolidation_handler import (
    ListConsolidationsHandler,
    ShowConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import ISimilarRecordFinder
from noesis.bounded_context.knowledge.application.services.schema_steps import require_steps
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    KnowledgePersistence,
    build_knowledge_persistence,
)
from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge import (
    SimilarRecordFinderAdapter,
)
from noesis.core import Environment
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .knowledge_handlers_builder import EXTRA_SCHEMA_STEPS
from .retrieval_handlers_builder import REQUIRED_STEPS, build_retrieval


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidationHandlers:
    """The consolidation actions of one invocation, wired.

    Attributes:
        scan: Find accepted Knowledge that may overlap (read-only).
        propose: Propose a successor for overlapping originals.
        show: Show one consolidation.
        list_consolidations: List consolidations of a project or the space-wide records.
        accept: Accept a consolidation's successor and assertions.
        reject: Dismiss a consolidation and retract its proposals.
        persistence: The store adapters (for the schema checks of the composition root).
    """

    scan: ScanConsolidationCandidatesHandler
    propose: ProposeConsolidationHandler
    show: ShowConsolidationHandler
    list_consolidations: ListConsolidationsHandler
    accept: AcceptConsolidationHandler
    reject: RejectConsolidationHandler
    persistence: KnowledgePersistence


def build_consolidation(
    client: Neo4jClient,
    environment: Environment,
    *,
    finder: ISimilarRecordFinder | None = None,
) -> ConsolidationHandlers:
    """Wire the handlers over `client` (the caller closes it); opens no connection.

    Args:
        client: The invocation's Neo4j client.
        environment: Loaded settings.
        finder: Similar-records lookup to use instead of Retrieval's (tests).
    """
    clock: IClock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    similar: ISimilarRecordFinder = finder or SimilarRecordFinderAdapter(
        build_retrieval(client, environment).find_similar
    )
    return ConsolidationHandlers(
        scan=ScanConsolidationCandidatesHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            finder=similar,
        ),
        propose=ProposeConsolidationHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            states=persistence.review_state_read_repository,
            read_repository=persistence.consolidation_read_repository,
        ),
        show=ShowConsolidationHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            states=persistence.review_state_read_repository,
        ),
        list_consolidations=ListConsolidationsHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        accept=AcceptConsolidationHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            states=persistence.review_state_read_repository,
            read_repository=persistence.consolidation_read_repository,
        ),
        reject=RejectConsolidationHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            states=persistence.review_state_read_repository,
            read_repository=persistence.consolidation_read_repository,
        ),
        persistence=persistence,
    )


@asynccontextmanager
async def open_consolidation(
    environment: Environment, *, needs_similarity: bool = False
) -> AsyncIterator[ConsolidationHandlers]:
    """Handlers over a client that is closed when the block ends, however it ends.

    Args:
        environment: Loaded settings.
        needs_similarity: Check the change-feed, full-text and cursor steps scan relies on.

    Raises:
        InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set.
        StoreNotInitialisedError: `needs_similarity` and a Retrieval schema step is missing.
    """
    async with Neo4jClient(environment.knowledge.neo4j_connection()) as client:
        handlers: ConsolidationHandlers = build_consolidation(client, environment)
        if needs_similarity:
            await require_steps(handlers.persistence.schema, *REQUIRED_STEPS)
        yield handlers


async def with_consolidation[T](
    environment: Environment,
    use: Callable[[ConsolidationHandlers], Awaitable[T]],
    *,
    needs_similarity: bool = False,
) -> T:
    """Run `use` over the invocation's handlers and close the client afterwards."""
    async with open_consolidation(environment, needs_similarity=needs_similarity) as handlers:
        return await use(handlers)
