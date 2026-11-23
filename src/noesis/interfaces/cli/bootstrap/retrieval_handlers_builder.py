"""Wires the Retrieval handlers over the invocation's Neo4j client, and the index sync trigger.

Projections and candidate sources are registered in one place, `registered_projections`. C5b
registers the `semantic` writer and source there (D30) according to
`NOESIS_RETRIEVAL_SEMANTIC_MODE`: `resident` (default) talks to a running
`noesis index embedder serve`; `per-call` loads the model in this process, and registers the
source only for explicit opt-ins; `off`, or the optional `semantic` extra not installed,
registers nothing and search stays lexical+graph.
"""

import asyncio
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

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
from noesis.bounded_context.retrieval.application.handlers.queries.unified_search_handler import (
    UnifiedSearchHandler,
)
from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    ICandidateSource,
)
from noesis.bounded_context.retrieval.application.ports.embedding import (
    EmbedderUnavailableError,
    ITextEmbedder,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_cursor_store import (
    IIndexCursorStore,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import IIndexWriter
from noesis.bounded_context.retrieval.application.services.briefing_redactor import BriefingRedactor
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.application.services.resource_facts_service import (
    ResourceFactsService,
)
from noesis.bounded_context.retrieval.domain.enums import SemanticModeEnum
from noesis.bounded_context.retrieval.domain.value_objects import EmbeddingProfile
from noesis.bounded_context.retrieval.infrastructure.inbound.embedder_runtime.unix_socket_embedder_server import (
    SocketInUseError,
    UnixSocketEmbedderServer,
    claim_socket_path,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.briefing.claude_cli_briefing_adapter import (
    ClaudeCliBriefingAdapter,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.embedder_protocol import (
    SocketPathTooLongError,
    resolve_socket_path,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.http_fetch import (
    https_fetch,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    ModelCache,
    ModelCacheError,
    PreparedModelDto,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.semantic_runtime_probe import (
    SETUP_NEXT_STEP,
    SemanticRuntimeProbe,
    semantic_dependency_installed,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.socket_text_embedder import (
    SocketTextEmbedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence import (
    RETRIEVAL_INDEX_STATEMENTS,
    RETRIEVAL_INDEX_STEP,
    RETRIEVAL_SEMANTIC_STATEMENTS,
    RETRIEVAL_SEMANTIC_STEP,
    Neo4jIndexCursorStoreAdapter,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic import (
    SEMANTIC_KIND,
    Neo4jSemanticCandidateSource,
    Neo4jSemanticProjectionAdapter,
    Neo4jVectorIndexInspector,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic.neo4j_vector_index_inspector import (
    check_semantic_vector_index,
)
from noesis.core import Environment
from noesis.exceptions import (
    InvalidConfigurationError,
    SemanticIndexUnavailableError,
    SpaceNotFoundError,
)
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

RETRIEVAL_INDEX_SCHEMA_STEP: Neo4jSchemaStep = Neo4jSchemaStep(
    name=RETRIEVAL_INDEX_STEP, statements=RETRIEVAL_INDEX_STATEMENTS
)

RETRIEVAL_SEMANTIC_SCHEMA_STEP: Neo4jSchemaStep = Neo4jSchemaStep(
    name=RETRIEVAL_SEMANTIC_STEP,
    statements=RETRIEVAL_SEMANTIC_STATEMENTS,
    check=check_semantic_vector_index,
)

RETRIEVAL_SCHEMA_STEPS: tuple[Neo4jSchemaStep, ...] = (
    CHANGE_FEED_SCHEMA_STEP,
    KNOWLEDGE_FULLTEXT_SCHEMA_STEP,
    RETRIEVAL_INDEX_SCHEMA_STEP,
    RETRIEVAL_SEMANTIC_SCHEMA_STEP,
)
"""The schema steps C5a and C5b register with `store init`, in application order."""

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


def semantic_mode(environment: Environment) -> SemanticModeEnum:
    """The configured semantic mode."""
    return SemanticModeEnum(environment.retrieval.retrieval_semantic_mode)


def model_cache(environment: Environment) -> ModelCache:
    """The pinned model's cache under the configured directory."""
    return ModelCache(environment.retrieval.retrieval_model_cache_dir)


def embedder_socket(environment: Environment) -> Path:
    """The resident embedder's socket for this cache and profile.

    Under the runtime directory, or `/tmp/noesis-<uid>` when that path would exceed the Unix
    socket length limit.

    Raises:
        InvalidConfigurationError: No candidate path fits the limit.
    """
    cache: ModelCache = model_cache(environment)
    root: Path = environment.retrieval.retrieval_model_cache_dir
    try:
        return resolve_socket_path(
            environment.retrieval.retrieval_runtime_dir,
            cache_root=root,
            profile_hash=cache.artifact.profile().fingerprint(),
        )
    except SocketPathTooLongError as error:
        raise InvalidConfigurationError(
            f"The embedder socket path is too long: {error}.",
            {"runtime_dir": str(environment.retrieval.retrieval_runtime_dir)},
            next_steps=["Set NOESIS_RETRIEVAL_RUNTIME_DIR to a short directory you own."],
        ) from error


def prepare_semantic_model(environment: Environment) -> PreparedModelDto:
    """Download (when missing), verify and cache the pinned model; the only download path.

    Raises:
        SemanticIndexUnavailableError: The download or verification failed.
    """
    cache: ModelCache = model_cache(environment)
    try:
        return cache.prepare(https_fetch)
    except (ModelCacheError, OSError, ValueError) as error:
        raise SemanticIndexUnavailableError(
            f"The semantic model could not be prepared: {error}",
            {"model": cache.artifact.model, "directory": str(cache.directory)},
            next_steps=["Check the network and retry `noesis index model prepare`."],
        ) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class ResidentEmbedder:
    """A loaded model ready to serve on its private socket.

    Attributes:
        server: The socket server (not listening yet).
        socket: Where it will listen.
        profile_hash: The profile it serves.
    """

    server: UnixSocketEmbedderServer
    socket: Path
    profile_hash: str


def _cannot_listen(socket: Path, error: Exception) -> SemanticIndexUnavailableError:
    return SemanticIndexUnavailableError(
        f"The embedder cannot listen: {error}",
        {"socket": str(socket)},
        next_steps=["Stop the other embedder, or check the socket directory's owner."],
    )


def build_resident_embedder(environment: Environment) -> ResidentEmbedder:
    """Check the dependency and the socket path first (cheap), then load the model once.

    Raises:
        SemanticIndexUnavailableError: The optional extra is missing, another embedder listens
            or the socket path belongs to another user, or the model is not prepared.
        InvalidConfigurationError: No socket path fits the Unix socket length limit.
    """
    if not semantic_dependency_installed():
        raise SemanticIndexUnavailableError(
            "The optional semantic dependencies are not installed.",
            {"extra": "semantic"},
            next_steps=[SETUP_NEXT_STEP],
        )
    socket: Path = embedder_socket(environment)
    try:
        claim_socket_path(socket)
    except (SocketInUseError, PermissionError) as error:
        raise _cannot_listen(socket, error) from error
    from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
        load_engine,
    )

    cache: ModelCache = model_cache(environment)
    try:
        engine = load_engine(cache, threads=environment.retrieval.retrieval_embedder_threads)
    except EmbedderUnavailableError as error:
        raise SemanticIndexUnavailableError(
            f"The embedder cannot start: {error}",
            {"directory": str(cache.directory)},
            next_steps=["Run `noesis index model prepare`."],
        ) from error
    return ResidentEmbedder(
        server=UnixSocketEmbedderServer(engine, socket),
        socket=socket,
        profile_hash=engine.profile.fingerprint(),
    )


async def serve_resident_embedder(
    embedder: ResidentEmbedder, stop: asyncio.Event, on_listening: Callable[[Path], None]
) -> None:
    """Listen, call `on_listening`, serve until `stop` is set, then remove the socket.

    Raises:
        SemanticIndexUnavailableError: Another embedder took the socket meanwhile, or its
            directory belongs to another user.
    """
    try:
        await embedder.server.start()
    except (SocketInUseError, PermissionError) as error:
        raise _cannot_listen(embedder.socket, error) from error
    on_listening(embedder.socket)
    await embedder.server.serve_until(stop)


def _embedder(environment: Environment, mode: SemanticModeEnum) -> ITextEmbedder:
    """The embedder of `mode`; the in-process one is imported only here (numpy is optional)."""
    cache: ModelCache = model_cache(environment)
    profile: EmbeddingProfile = cache.artifact.profile()
    if mode is SemanticModeEnum.RESIDENT:
        return SocketTextEmbedder(profile, embedder_socket(environment))
    from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.in_process_text_embedder import (
        InProcessTextEmbedder,
    )
    from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
        load_engine,
    )

    threads: int | None = environment.retrieval.retrieval_embedder_threads
    return InProcessTextEmbedder(profile, lambda: load_engine(cache, threads=threads))


def registered_projections(
    client: Neo4jClient, environment: Environment, *, semantic_opt_in: bool = False
) -> RegisteredProjections:
    """The one place projections are registered.

    `semantic` is registered when the mode is not `off` and the optional extra is installed.
    In `per-call` mode its source is registered only with `semantic_opt_in` (an explicit
    `search --semantic` or `--require-semantic`), so no ordinary call pays the model load.
    """
    mode: SemanticModeEnum = semantic_mode(environment)
    if mode is SemanticModeEnum.OFF or not semantic_dependency_installed():
        return RegisteredProjections(writers=(), candidate_sources=())
    embedder: ITextEmbedder = _embedder(environment, mode)
    cursors = Neo4jIndexCursorStoreAdapter(client, SystemClockAdapter())
    writer = Neo4jSemanticProjectionAdapter(client, embedder, cursors)
    sources: tuple[ICandidateSource, ...] = ()
    if mode is SemanticModeEnum.RESIDENT or semantic_opt_in:
        sources = (
            Neo4jSemanticCandidateSource(client, embedder, Neo4jVectorIndexInspector(client)),
        )
    return RegisteredProjections(writers=(writer,), candidate_sources=sources, cursors=cursors)


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
        recall: The recall pipeline, also the briefing of the unified search.
        unified_search: Records, resources, requirements and next actions in one answer.
    """

    search: SearchRecordsHandler
    find_similar: FindSimilarRecordsHandler
    sync_index: SyncIndexHandler
    rebuild_index: RebuildIndexHandler
    index_status: GetIndexStatusHandler
    searcher: RecordSearcher
    projection_kinds: tuple[str, ...]
    recall: RecallHandler | None = None
    unified_search: UnifiedSearchHandler | None = None


def build_retrieval(
    client: Neo4jClient, environment: Environment, *, semantic_opt_in: bool = False
) -> RetrievalHandlers:
    """Wire the handlers over `client` (the caller closes it); opens no connection.

    Raises:
        InvalidConfigurationError: Two registered projections share a `kind`.
    """
    registered: RegisteredProjections = registered_projections(
        client, environment, semantic_opt_in=semantic_opt_in
    )
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
    from .knowledge_handlers_builder import (  # import cycle
        build_catalog_availability_adapter,
        build_resource_catalog_reader,
    )

    reviews = ReviewReadersAdapter(client)
    settings = environment.retrieval
    ttl: int = settings.index_lock_ttl_seconds
    availability = build_catalog_availability_adapter(client, environment)
    recall = RecallHandler(
        searcher,
        indexables,
        reviews=reviews,
        recommendations=reviews,
        catalog=availability,
        model=ClaudeCliBriefingAdapter(
            claude_bin=settings.retrieval_briefing_claude_bin,
            timeout_seconds=settings.retrieval_briefing_timeout_seconds,
            max_budget_usd=settings.retrieval_briefing_max_budget_usd,
        ),
        redactor=BriefingRedactor(),
        max_evidence_chars=settings.retrieval_briefing_max_evidence_chars,
    )
    return RetrievalHandlers(
        recall=recall,
        unified_search=UnifiedSearchHandler(
            searcher,
            resources=build_resource_catalog_reader(client, environment),
            facts=ResourceFactsService(
                reviews=reviews,
                recommendations=reviews,
                assertions=reviews,
                availability=availability,
            ),
            briefing=recall,
            clock=clock,
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
            writers=registered.writers,
            cursors=cursors,
            feed=feed,
            states=states,
            semantic_probe=_probe(client, environment),
        ),
        searcher=searcher,
        projection_kinds=kinds,
    )


def _probe(client: Neo4jClient, environment: Environment) -> SemanticRuntimeProbe:
    mode: SemanticModeEnum = semantic_mode(environment)
    cache: ModelCache = model_cache(environment)
    return SemanticRuntimeProbe(
        mode=mode,
        cache=cache,
        client=(
            SocketTextEmbedder(cache.artifact.profile(), embedder_socket(environment))
            if mode is SemanticModeEnum.RESIDENT
            else None
        ),
        inspector=Neo4jVectorIndexInspector(client),
    )


async def with_retrieval[T](
    environment: Environment,
    use: Callable[[RetrievalHandlers, str], Awaitable[T]],
    *,
    semantic_opt_in: bool = False,
    indexing: bool = False,
) -> T:
    """Run `use(handlers, space_id)` over a client that is closed afterwards.

    The C5a schema steps must be applied and the configured space must exist; both are checked
    before `use` runs and nothing is written. An `indexing` command with the semantic
    projection registered also needs the `retrieval_semantic` step; searches do not (a missing
    vector index makes semantic unavailable, not the search). An unreachable store surfaces from
    the first store call as `INTEGRATION_103`.

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
        if indexing and SEMANTIC_KIND in registered_projection_kinds(environment):
            await require_steps(persistence.schema, RETRIEVAL_SEMANTIC_STEP)
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
        return await use(
            build_retrieval(client, environment, semantic_opt_in=semantic_opt_in), space_id.value
        )


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
    "ResidentEmbedder",
    "RetrievalHandlers",
    "build_resident_embedder",
    "build_retrieval",
    "embedder_socket",
    "model_cache",
    "prepare_semantic_model",
    "registered_projection_kinds",
    "registered_projections",
    "semantic_mode",
    "serve_resident_embedder",
    "start_detached",
    "trigger_index_sync",
    "with_retrieval",
]
