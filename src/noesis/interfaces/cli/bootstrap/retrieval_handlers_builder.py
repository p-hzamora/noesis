"""Wires the Retrieval handlers over the invocation's Neo4j client, and the index sync trigger.

Projections and candidate sources are registered in one place, `registered_projections`; C5a's
production wiring registers none (D-025), so every `index` command reports that nothing is
registered and a capture starts no detached sync.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CHANGE_FEED_STEP,
    KNOWLEDGE_FULLTEXT_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key, SpaceId
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_text_search_adapter import (
    Neo4jRecordTextSearchAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.review_readers_adapter import (
    ReviewReadersAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CHANGE_FEED_SCHEMA_STEP,
    KNOWLEDGE_FULLTEXT_SCHEMA_STEP,
    KnowledgePersistence,
    Neo4jSchemaStep,
    build_knowledge_persistence,
)
from noesis.bounded_context.retrieval.application.handlers.commands.rebuild_index_handler import (
    RebuildIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.get_index_status_handler import (
    GetIndexStatusHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.recall_handler import (
    RecallHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.search_records_handler import (
    SearchRecordsHandler,
)
from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    ICandidateSource,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_cursor_store import (
    IIndexCursorStore,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import IIndexWriter
from noesis.bounded_context.retrieval.application.services.briefing_redactor import BriefingRedactor
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.infrastructure.outbound.briefing.claude_cli_briefing_adapter import (
    ClaudeCliBriefingAdapter,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence import (
    RETRIEVAL_INDEX_STATEMENTS,
    RETRIEVAL_INDEX_STEP,
    Neo4jIndexCursorStoreAdapter,
)
from noesis.core import Environment
from noesis.exceptions import InvalidConfigurationError, SpaceNotFoundError
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

RETRIEVAL_INDEX_SCHEMA_STEP: Neo4jSchemaStep = Neo4jSchemaStep(
    name=RETRIEVAL_INDEX_STEP, statements=RETRIEVAL_INDEX_STATEMENTS
)

RETRIEVAL_SCHEMA_STEPS: tuple[Neo4jSchemaStep, ...] = (
    CHANGE_FEED_SCHEMA_STEP,
    KNOWLEDGE_FULLTEXT_SCHEMA_STEP,
    RETRIEVAL_INDEX_SCHEMA_STEP,
)
"""The schema steps C5a registers with `store init`, in application order."""

REQUIRED_STEPS: tuple[str, ...] = (CHANGE_FEED_STEP, KNOWLEDGE_FULLTEXT_STEP, RETRIEVAL_INDEX_STEP)

type ProcessStarter = Callable[[Sequence[str]], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisteredProjections:
    """The projections and candidate sources of one process.

    Attributes:
        writers: Projection writers; each `kind` is unique.
        candidate_sources: Sources that answer from a projection.
        cursors: Cursor store to use instead of the Neo4j one (tests, option A's local file).
    """

    writers: tuple[IIndexWriter, ...]
    candidate_sources: tuple[ICandidateSource, ...]
    cursors: IIndexCursorStore | None = None


def registered_projections(client: Neo4jClient, environment: Environment) -> RegisteredProjections:
    """The one place projections are registered; production registers none (D-025)."""
    return RegisteredProjections(writers=(), candidate_sources=())


def registered_projection_kinds(environment: Environment) -> tuple[str, ...]:
    """Names of the registered projections, read without contacting the store.

    The driver connects lazily, so the unused client built here opens no connection.
    """
    client = Neo4jClient(environment.knowledge.neo4j_connection())
    return tuple(writer.kind for writer in registered_projections(client, environment).writers)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalHandlers:
    """The search and index actions of one invocation, wired.

    Attributes:
        search: Search the records.
        find_similar: Find the records most like an anchor.
        sync_index: Bring projections up to date.
        rebuild_index: Rebuild projections.
        index_status: Report cursors, lag and divergences.
        searcher: The search pipeline (for other contexts' adapters).
        projection_kinds: Names of the registered projections.
    """

    search: SearchRecordsHandler
    find_similar: FindSimilarRecordsHandler
    sync_index: SyncIndexHandler
    rebuild_index: RebuildIndexHandler
    index_status: GetIndexStatusHandler
    searcher: RecordSearcher
    projection_kinds: tuple[str, ...]
    recall: RecallHandler | None = None


def build_retrieval(client: Neo4jClient, environment: Environment) -> RetrievalHandlers:
    """Wire the handlers over `client` (the caller closes it); opens no connection.

    Raises:
        InvalidConfigurationError: Two registered projections share a `kind`.
    """
    registered: RegisteredProjections = registered_projections(client, environment)
    kinds: tuple[str, ...] = tuple(writer.kind for writer in registered.writers)
    duplicates: list[str] = sorted({kind for kind in kinds if kinds.count(kind) > 1})
    if duplicates:
        raise InvalidConfigurationError(
            f"Two index projections share a name: {', '.join(duplicates)}.",
            {"duplicate_projections": [*duplicates]},
            next_steps=["Register each projection under a unique `kind`."],
        )
    clock: IClock = SystemClockAdapter()
    cursors: IIndexCursorStore = registered.cursors or Neo4jIndexCursorStoreAdapter(client, clock)
    feed = Neo4jRecordChangeFeedAdapter(client)
    states = Neo4jRecordStateReaderAdapter(client)
    indexables = Neo4jIndexableRecordReaderAdapter(client)
    searcher = RecordSearcher(
        Neo4jRecordTextSearchAdapter(client),
        states,
        Neo4jRecordNeighbourReaderAdapter(client),
        indexables,
        registered.candidate_sources,
        cursors,
        feed,
        projection_kinds=kinds,
    )
    from .knowledge_handlers_builder import build_catalog_availability_adapter

    reviews = ReviewReadersAdapter(client)
    settings = environment.retrieval
    ttl: int = settings.index_lock_ttl_seconds
    return RetrievalHandlers(
        recall=RecallHandler(
            searcher,
            indexables,
            reviews=reviews,
            recommendations=reviews,
            catalog=build_catalog_availability_adapter(client, environment),
            model=ClaudeCliBriefingAdapter(
                claude_bin=settings.retrieval_briefing_claude_bin,
                timeout_seconds=settings.retrieval_briefing_timeout_seconds,
                max_budget_usd=settings.retrieval_briefing_max_budget_usd,
            ),
            redactor=BriefingRedactor(),
            max_evidence_chars=settings.retrieval_briefing_max_evidence_chars,
        ),
        search=SearchRecordsHandler(searcher),
        find_similar=FindSimilarRecordsHandler(searcher),
        sync_index=SyncIndexHandler(
            writers=registered.writers,
            cursors=cursors,
            feed=feed,
            states=states,
            indexables=indexables,
            lock_ttl_seconds=ttl,
        ),
        rebuild_index=RebuildIndexHandler(
            writers=registered.writers,
            cursors=cursors,
            feed=feed,
            states=states,
            indexables=indexables,
            lock_ttl_seconds=ttl,
        ),
        index_status=GetIndexStatusHandler(
            writers=registered.writers, cursors=cursors, feed=feed, states=states
        ),
        searcher=searcher,
        projection_kinds=kinds,
    )


async def with_retrieval[T](
    environment: Environment, use: Callable[[RetrievalHandlers, str], Awaitable[T]]
) -> T:
    """Run `use(handlers, space_id)` over a client that is closed afterwards.

    The C5a schema steps must be applied and the configured space must exist; both are checked
    before `use` runs and nothing is written. An unreachable store surfaces from the first
    store call as `INTEGRATION_103`.

    Raises:
        InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set, or two projections share
            a name.
        StoreNotInitialisedError: A C5a schema step is missing.
        SpaceNotFoundError: The configured space key is unknown.
    """
    from .knowledge_handlers_builder import EXTRA_SCHEMA_STEPS  # breaks an import cycle

    async with Neo4jClient(environment.knowledge.neo4j_connection()) as client:
        persistence: KnowledgePersistence = build_knowledge_persistence(
            client, clock=SystemClockAdapter(), extra_steps=EXTRA_SCHEMA_STEPS
        )
        await require_steps(persistence.schema, *REQUIRED_STEPS)
        space_key: str = environment.knowledge.knowledge_space
        space_id: SpaceId | None = await persistence.read_repository.get_space_id(
            Key(value=space_key)
        )
        if space_id is None:
            raise SpaceNotFoundError(
                f"No knowledge space has the key {space_key!r}.",
                {"space_key": space_key},
                next_steps=["Run `noesis store init` or check the configured space key."],
            )
        return await use(build_retrieval(client, environment), space_id.value)


class IndexSyncTrigger:
    """Starts a detached `index sync` after a record command commits.

    Only when at least one projection is registered; with none, nothing is started (FR-024).

    Args:
        registered: The process's projections.
        start_process: Starts `argv` detached and returns at once; injectable for tests.
        command: How a child re-enters noesis with the same configuration file.
    """

    def __init__(
        self,
        *,
        registered: RegisteredProjections,
        command: Sequence[str],
        start_process: ProcessStarter | None = None,
    ) -> None:
        self._registered: RegisteredProjections = registered
        self._command: tuple[str, ...] = tuple(command)
        self._start_process: ProcessStarter = start_process or start_detached

    def trigger(self) -> None:
        """Start the sync, unless no projection is registered or the process cannot start."""
        if not self._registered.writers:
            return
        try:
            self._start_process([*self._command, "index", "sync", "--json"])
        except OSError:
            return  # the next sync (or a rebuild) catches up; a capture must not fail for it

    @classmethod
    def for_environment(cls, client: Neo4jClient, environment: Environment) -> IndexSyncTrigger:
        """A trigger over the registered projections that re-enters with the same `.env`."""
        return cls(
            registered=registered_projections(client, environment),
            command=[sys.executable, "-m", "noesis", "--env-file", str(environment.env_file)],
        )


def trigger_index_sync(environment: Environment) -> None:
    """Start the detached sync after a committed write; a no-op with no projection registered."""
    client = Neo4jClient(environment.knowledge.neo4j_connection())  # lazy: no connection opened
    IndexSyncTrigger.for_environment(client, environment).trigger()


def start_detached(argv: Sequence[str]) -> None:
    """Start `argv` in a new session with no stdio and do not wait for it.

    Raises:
        OSError: The executable is missing or cannot be started.
    """
    executable: str | None = argv[0] if os.sep in argv[0] else shutil.which(argv[0])
    if executable is None:
        raise FileNotFoundError(f"{argv[0]} not found on PATH")
    process = subprocess.Popen(  # noqa: S603  # argv is built from our own fixed command
        [executable, *argv[1:]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    process.returncode = 0  # detach on purpose: suppresses the "still running" ResourceWarning


__all__ = [
    "RETRIEVAL_SCHEMA_STEPS",
    "IndexSyncTrigger",
    "RegisteredProjections",
    "RetrievalHandlers",
    "build_retrieval",
    "registered_projection_kinds",
    "registered_projections",
    "start_detached",
    "trigger_index_sync",
    "with_retrieval",
]
