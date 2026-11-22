"""Wires the Knowledge handlers over one Neo4j client per invocation.

The client is built when a command starts and closed when it ends (`open_knowledge`). Building
it opens no connection: the driver is created on the first query, so `--help`, usage errors and
a missing password never reach this module or the store.
"""

import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.knowledge.application.dtos import RuntimeEnum
from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.bulk_accept_knowledge_by_tag_handler import (
    BulkAcceptKnowledgeByTagHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.sync_runtime_catalog_handler import (
    SyncRuntimeCatalogHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.repair_supersession_effects_handler import (
    RepairSupersessionEffectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_assertion_handler import (
    RetractAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RetractKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog import (
    CheckCatalogAvailabilityHandler,
    GetCatalogEntryHandler,
    ListCatalogEntriesHandler,
    ScanRuntimeCatalogHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_by_subjects_handler import (
    ListAssertionsBySubjectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_handler import (
    ListAssertionsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_decisions_handler import (
    ListReviewDecisionsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueHandler,
)
from noesis.bounded_context.knowledge.application.ports.runtime import (
    IHostToolProbe,
    IRuntimeInventoryProbe,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval import (
    CatalogAvailabilityInboundAdapter,
    Neo4jResourceCatalogReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CATALOG_DISCOVERY_SCHEMA_STEP,
    CATALOG_FULLTEXT_SCHEMA_STEP,
    CATALOG_SCHEMA_STEP,
    CONSOLIDATION_SCHEMA_STEP,
    CORE_SCHEMA_STEP,
    REVIEW_SCHEMA_STEP,
    KnowledgePersistence,
    Neo4jSchemaStep,
    build_knowledge_persistence,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.links_schema_step import (
    LINKS_SCHEMA_STEP,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime import (
    ClaudeCodeRuntimeInventoryAdapter,
    CodexRuntimeInventoryAdapter,
    PathHostToolProbeAdapter,
)
from noesis.core import Environment, load_claude_code_settings
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .retrieval_handlers_builder import RETRIEVAL_SCHEMA_STEPS

EXTRA_SCHEMA_STEPS: tuple[Neo4jSchemaStep, ...] = (
    REVIEW_SCHEMA_STEP,
    *RETRIEVAL_SCHEMA_STEPS,
    CATALOG_SCHEMA_STEP,
    CATALOG_DISCOVERY_SCHEMA_STEP,
    CATALOG_FULLTEXT_SCHEMA_STEP,
    LINKS_SCHEMA_STEP,
    CONSOLIDATION_SCHEMA_STEP,
)
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
        propose_assertion: Propose an assertion about two records.
        accept_knowledge: Accept proposed knowledge.
        accept_assertion: Accept a proposed assertion (and run a supersession effect).
        retract_knowledge: Reject or retract knowledge.
        retract_assertion: Reject or retract an assertion.
        apply_supersession: Run the supersession effect of an accepted `supersedes`.
        bulk_accept: Accept every proposed knowledge record carrying a tag.
        repair_supersession: Run every pending supersession effect.
        list_review_queue: A page of the review queue.
        list_assertions: Assertions in which a record plays a part.
        list_assertions_by_subjects: Assertion summaries by subject (Retrieval's read).
        list_review_decisions: The decision history of a record.
        get_review_states: Review states of records (Retrieval's read).
        register_catalog_entry: Register a capability in the catalog.
        revise_catalog_entry: Revise a catalog entry.
        list_catalog_entries: List catalog entries.
        get_catalog_entry: Show one catalog entry.
        check_catalog_availability: Check what is installed against the catalog.
        scan_runtime_catalog: Compare what is installed with the catalog.
        sync_runtime_catalog: Register and revise entries for what is installed.
    """

    capture_knowledge: CaptureKnowledgeHandler
    capture_experience: CaptureExperienceHandler
    revise_knowledge: ReviseKnowledgeHandler
    get_record: GetRecordHandler
    initialise_store: InitialiseStoreHandler
    propose_assertion: ProposeAssertionHandler
    accept_knowledge: AcceptKnowledgeHandler
    accept_assertion: AcceptAssertionHandler
    retract_knowledge: RetractKnowledgeHandler
    retract_assertion: RetractAssertionHandler
    apply_supersession: ApplySupersessionHandler
    bulk_accept: BulkAcceptKnowledgeByTagHandler
    repair_supersession: RepairSupersessionEffectsHandler
    list_review_queue: ListReviewQueueHandler
    list_assertions: ListAssertionsHandler
    list_assertions_by_subjects: ListAssertionsBySubjectsHandler
    list_review_decisions: ListReviewDecisionsHandler
    get_review_states: GetReviewStatesHandler
    register_catalog_entry: RegisterCatalogEntryHandler
    revise_catalog_entry: ReviseCatalogEntryHandler
    list_catalog_entries: ListCatalogEntriesHandler
    get_catalog_entry: GetCatalogEntryHandler
    check_catalog_availability: CheckCatalogAvailabilityHandler
    scan_runtime_catalog: ScanRuntimeCatalogHandler
    sync_runtime_catalog: SyncRuntimeCatalogHandler


def _catalog_probes(
    clock: IClock, environment: Environment
) -> tuple[Mapping[RuntimeEnum, IRuntimeInventoryProbe], IHostToolProbe]:
    """The runtime probes and the `PATH` probe of this host, project and user."""
    host: str = socket.gethostname()
    return (
        {
            RuntimeEnum.CLAUDE_CODE: ClaudeCodeRuntimeInventoryAdapter(
                config_dir=load_claude_code_settings().config_dir,
                project_root=Path.cwd(),
                clock=clock,
                host=host,
            ),
            RuntimeEnum.CODEX: CodexRuntimeInventoryAdapter(
                codex_home=environment.codex.codex_home, clock=clock, host=host
            ),
        },
        PathHostToolProbeAdapter(),
    )


def _check_handler(
    persistence: KnowledgePersistence,
    runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe],
    host_tools: IHostToolProbe,
) -> CheckCatalogAvailabilityHandler:
    return CheckCatalogAvailabilityHandler(
        read_repository=persistence.catalog_read_repository,
        records=persistence.read_repository,
        schema=persistence.schema,
        runtime_probes=runtime_probes,
        host_tools=host_tools,
    )


def build_catalog_availability_adapter(
    client: Neo4jClient, environment: Environment
) -> CatalogAvailabilityInboundAdapter:
    """Wire Retrieval's availability door over `client` (the caller closes it); opens no connection."""
    clock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    runtime_probes, host_tools = _catalog_probes(clock, environment)
    return CatalogAvailabilityInboundAdapter(
        check=_check_handler(persistence, runtime_probes, host_tools)
    )


def build_resource_catalog_reader(
    client: Neo4jClient, environment: Environment
) -> Neo4jResourceCatalogReaderAdapter:
    """Wire Retrieval's resource search over `client` (the caller closes it); opens no connection."""
    clock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    runtime_probes, _ = _catalog_probes(clock, environment)
    return Neo4jResourceCatalogReaderAdapter(client, persistence.schema, runtime_probes)


def build_knowledge(client: Neo4jClient, environment: Environment) -> KnowledgeHandlers:
    """Wire the handlers over `client` (the caller closes it); opens no connection."""
    clock = SystemClockAdapter()
    persistence: KnowledgePersistence = build_knowledge_persistence(
        client, clock=clock, extra_steps=EXTRA_SCHEMA_STEPS
    )
    runtime_probes, host_tools = _catalog_probes(clock, environment)
    register_catalog_entry = RegisterCatalogEntryHandler(
        uow_factory=persistence.uow_factory,
        clock=clock,
        ids=persistence.ids,
        schema=persistence.schema,
    )
    revise_catalog_entry = ReviseCatalogEntryHandler(
        uow_factory=persistence.uow_factory,
        clock=clock,
        ids=persistence.ids,
        schema=persistence.schema,
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
        propose_assertion=ProposeAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        accept_knowledge=AcceptKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        accept_assertion=AcceptAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        retract_knowledge=RetractKnowledgeHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        retract_assertion=RetractAssertionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        apply_supersession=ApplySupersessionHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
        ),
        bulk_accept=BulkAcceptKnowledgeByTagHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            queue_reader=persistence.review_queue_read_repository,
        ),
        repair_supersession=RepairSupersessionEffectsHandler(
            uow_factory=persistence.uow_factory,
            clock=clock,
            ids=persistence.ids,
            schema=persistence.schema,
            state_reader=persistence.review_state_read_repository,
        ),
        list_review_queue=ListReviewQueueHandler(
            read_repository=persistence.review_queue_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        list_assertions=ListAssertionsHandler(
            read_repository=persistence.assertion_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        list_assertions_by_subjects=ListAssertionsBySubjectsHandler(
            read_repository=persistence.assertion_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        list_review_decisions=ListReviewDecisionsHandler(
            read_repository=persistence.review_decision_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        get_review_states=GetReviewStatesHandler(
            read_repository=persistence.review_state_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        register_catalog_entry=register_catalog_entry,
        revise_catalog_entry=revise_catalog_entry,
        list_catalog_entries=ListCatalogEntriesHandler(
            read_repository=persistence.catalog_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        get_catalog_entry=GetCatalogEntryHandler(
            read_repository=persistence.catalog_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        ),
        check_catalog_availability=_check_handler(persistence, runtime_probes, host_tools),
        scan_runtime_catalog=ScanRuntimeCatalogHandler(
            read_repository=persistence.catalog_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            runtime_probes=runtime_probes,
            host_tools=host_tools,
        ),
        sync_runtime_catalog=SyncRuntimeCatalogHandler(
            read_repository=persistence.catalog_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            runtime_probes=runtime_probes,
            register=register_catalog_entry,
            revise=revise_catalog_entry,
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
