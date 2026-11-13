"""Wires the Notes context's handlers."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from noesis.bounded_context.notes.application.dtos import NoteContentDto, RecallBriefingDto
from noesis.bounded_context.notes.application.handlers.commands import (
    ApplyCurationHandler,
    CurateWorkBriefHandler,
    RetryParkedCurationHandler,
)
from noesis.bounded_context.notes.application.handlers.queries import (
    ListNotesHandler,
    ListParkedCurationsHandler,
    RecallNotesHandler,
    SearchNotesHandler,
)
from noesis.bounded_context.notes.application.ports.curation import ICurator
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.recall import IRecallAgent
from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.application.services.manifest import (
    Manifest,
    SourceRoleEnum,
    SourceSpec,
    SourceTypeEnum,
)
from noesis.bounded_context.notes.domain.policies import AutoCurationPolicy
from noesis.bounded_context.notes.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
    default_system_prompt,
)
from noesis.bounded_context.notes.infrastructure.outbound.failures import (
    JsonFileApplyFailureLogAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.ids import UlidNoteIdGeneratorAdapter
from noesis.bounded_context.notes.infrastructure.outbound.manifest import (
    YamlManifestProviderAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.queue import (
    JsonFileParkedCurationQueueAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.recall import (
    ClaudeCliRecallAgentAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FallbackNoteReadRepositoryAdapter,
    FilesystemNoteReadRepositoryAdapter,
    FilesystemNoteRepositoryAdapter,
    FilesystemNotesUnitOfWorkAdapter,
    McpNoteRepositoryAdapter,
    McpNotesUnitOfWorkAdapter,
    MultiSourceNoteReadRepositoryAdapter,
    ObsidianMcpNoteReadRepositoryAdapter,
    SourceReader,
    UnavailableNoteReadRepositoryAdapter,
    VectraNoteReadRepositoryAdapter,
    VectraNoteRepositoryAdapter,
    VectraNotesUnitOfWorkAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.bounded_context.notes.infrastructure.outbound.vectra import VectraCliClient
from noesis.core import Environment, RecallRuntimeEnum
from noesis.exceptions import (
    CuratorPromptUnreadableError,
    InvalidConfigurationError,
    NoteStorageError,
    VaultNotConfiguredError,
)
from noesis.shared_kernel.enums import SearchEngineEnum, WriterBackendEnum
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

from .obsidian_mcp_client_builder import build_obsidian_mcp_client

PARKED_FOLDER: tuple[str, ...] = ("notes", "parked")
APPLY_FAILED_FOLDER: tuple[str, ...] = ("notes", "apply-failed")
CLAUDE_EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")  # `claude --help`
MCP_FALLBACK_NOTICE: str = "Obsidian MCP unreachable, searched files instead"
VECTRA_FALLBACK_NOTICE: str = "vectra could not search, searched files instead"
VECTRA_SYNC_NOTICE: str = "Notes written, but vectra could not index them; run `vectra sync`"


@dataclass(frozen=True, slots=True, kw_only=True)
class NotesHandlers:
    """The Notes context's inbound actions, wired.

    Attributes:
        curate: Curate a work brief.
        retry: Retry a parked curation.
        search: Free-text note search.
        recall: Briefing (or ranked digest) of what the notes say about a task.
        list_notes: List notes.
        list_parked: List parked curations.
        notices: Messages the adapters raised while the handlers ran (e.g. the search fell
            back to files); the commands show them. Empty on the default backend.
    """

    curate: CurateWorkBriefHandler
    retry: RetryParkedCurationHandler
    search: SearchNotesHandler
    recall: RecallNotesHandler
    list_notes: ListNotesHandler
    list_parked: ListParkedCurationsHandler
    notices: list[str]


def _vault_not_configured() -> VaultNotConfiguredError:
    return VaultNotConfiguredError(
        "No vault folder is configured.",
        {"setting": "NOESIS_VAULT_DIR"},
        next_steps=["Run `noesis config init --vault-dir <folder>` or set NOESIS_VAULT_DIR."],
    )


def require_vault(environment: Environment) -> Path:
    """The configured vault folder.

    Raises:
        VaultNotConfiguredError: `NOESIS_VAULT_DIR` is not set.
    """
    vault: Path | None = environment.notes.vault_dir
    if vault is None:
        raise _vault_not_configured()
    return vault


def needs_vault(environment: Environment) -> bool:
    """Whether something still uses local files: the filesystem or vectra writer or search.

    Vectra indexes a folder, so its backends read and write the vault's files too.
    """
    settings = environment.notes
    return settings.writer_backend in {
        WriterBackendEnum.FILESYSTEM,
        WriterBackendEnum.VECTRA,
    } or settings.search_backend in {SearchEngineEnum.FILESYSTEM, SearchEngineEnum.VECTRA}


def curator_system_prompt(environment: Environment) -> str:
    """The curator's system prompt: the configured file, else the packaged one.

    Raises:
        CuratorPromptUnreadableError: `NOESIS_CURATOR_SYSTEM_PROMPT_FILE` cannot be read.
    """
    prompt_file: Path | None = environment.curator.system_prompt_file
    if prompt_file is None:
        return default_system_prompt()
    path: Path = prompt_file.expanduser()
    try:
        prompt: str = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CuratorPromptUnreadableError(
            f"Cannot read the curator system prompt {path}: {error}",
            {"setting": "NOESIS_CURATOR_SYSTEM_PROMPT_FILE", "path": str(path)},
            next_steps=[
                "Fix the file, or unset NOESIS_CURATOR_SYSTEM_PROMPT_FILE to use the packaged prompt."
            ],
        ) from error
    if not prompt.strip():
        raise CuratorPromptUnreadableError(
            f"The curator system prompt {path} is empty.",
            {"setting": "NOESIS_CURATOR_SYSTEM_PROMPT_FILE", "path": str(path)},
            next_steps=[
                "Write the prompt, or unset NOESIS_CURATOR_SYSTEM_PROMPT_FILE to use the packaged prompt."
            ],
        )
    return prompt


def build_curator(environment: Environment) -> ICurator:
    """The Claude CLI curator configured by `environment`."""
    return ClaudeCliCuratorAdapter(
        claude_bin=environment.curator.claude_bin,
        model=environment.curator.model,
        max_budget_usd=environment.curator.max_budget_usd,
        timeout_seconds=environment.curator.timeout_seconds,
        system_prompt=curator_system_prompt(environment),
    )


def build_recall_agent(environment: Environment) -> IRecallAgent:
    """The recall agent for `NOESIS_RECALL_RUNTIME`, asked for `NOESIS_RECALL_MODEL`.

    The runtime (the program that runs the agent) and the model (what it is asked to use) are
    separate settings; the model is passed through untouched.
    """
    settings = environment.recall
    match settings.runtime:
        case RecallRuntimeEnum.CLAUDE_CLI:
            if settings.effort and settings.effort not in CLAUDE_EFFORT_LEVELS:
                # the CLI itself accepts any text here and ignores it, so a typo would pass silently
                raise InvalidConfigurationError(
                    f"NOESIS_RECALL_EFFORT={settings.effort!r} is not an effort level of claude-cli.",
                    {"setting": "NOESIS_RECALL_EFFORT", "accepted": list(CLAUDE_EFFORT_LEVELS)},
                    next_steps=[
                        f"Use one of {', '.join(CLAUDE_EFFORT_LEVELS)}, or leave it empty."
                    ],
                )
            return ClaudeCliRecallAgentAdapter(
                claude_bin=settings.claude_bin,
                model=settings.model,
                effort=settings.effort,
                max_budget_usd=settings.max_budget_usd,
                timeout_seconds=settings.timeout_seconds,
            )
        case _ as unhandled:
            assert_never(unhandled)


class _LazyRecallAgent(IRecallAgent):
    """Builds the real agent on first use, so recall settings only matter when a briefing runs.

    A typo in `NOESIS_RECALL_EFFORT` must not break `notes curate` or `notes recall --no-synthesis`.
    """

    def __init__(self, build: Callable[[], IRecallAgent]) -> None:
        self._build: Callable[[], IRecallAgent] = build
        self._agent: IRecallAgent | None = None

    async def brief(
        self, task: str, notes: Sequence[NoteContentDto], *, target_tokens: int
    ) -> RecallBriefingDto:
        if self._agent is None:
            self._agent = self._build()
        return await self._agent.brief(task, notes, target_tokens=target_tokens)


def build_read_repository(
    environment: Environment, vault: Path | None, mapper: NoteMapper, notices: list[str]
) -> INoteReadRepository:
    """The note read repository for `NOESIS_SEARCH_BACKEND`, independent of the writer.

    `filesystem` (default) never touches the network. `obsidian-mcp` searches through Obsidian
    and degrades to the filesystem, appending one notice to `notices`, when it is unreachable.
    Without a vault (`vault` is None: writer `mcp` and search `obsidian-mcp`) there is nothing
    to fall back to: a search failure is raised and `notes list` fails with
    `VaultNotConfiguredError`. The same repository serves `notes search`, `notes list`
    and the curator's related-notes lookup.

    Raises:
        VaultNotConfiguredError: Search is `filesystem` and `vault` is None.
    """
    backend: SearchEngineEnum = environment.notes.search_backend
    match backend:
        case SearchEngineEnum.FILESYSTEM:
            if vault is None:
                raise _vault_not_configured()
            return FilesystemNoteReadRepositoryAdapter(vault, mapper)
        case SearchEngineEnum.OBSIDIAN_MCP:
            client = build_obsidian_mcp_client(environment)
            if vault is None:
                return ObsidianMcpNoteReadRepositoryAdapter(
                    client,
                    mapper,
                    listing=UnavailableNoteReadRepositoryAdapter(_vault_not_configured),
                )
            files = FilesystemNoteReadRepositoryAdapter(vault, mapper)
            return FallbackNoteReadRepositoryAdapter(
                ObsidianMcpNoteReadRepositoryAdapter(client, mapper, listing=files),
                files,
                on_fallback=lambda _error: notices.append(MCP_FALLBACK_NOTICE),
            )
        case SearchEngineEnum.VECTRA:
            if vault is None:
                raise _vault_not_configured()
            files = FilesystemNoteReadRepositoryAdapter(vault, mapper)
            return _vectra_reader(
                build_vectra_client(environment),
                environment.notes.vectra_collection,
                files,
                notices,
            )
        case _ as unhandled:
            assert_never(unhandled)


def build_vectra_client(environment: Environment) -> VectraCliClient:
    """The client of the `vectra` program (`NOESIS_VECTRA_BIN`, `NOESIS_VECTRA_TIMEOUT_SECONDS`)."""
    return VectraCliClient(
        vectra_bin=environment.notes.vectra_bin,
        timeout_seconds=environment.notes.vectra_timeout_seconds,
    )


def _vectra_reader(
    client: VectraCliClient,
    collection: str,
    files: INoteReadRepository,
    notices: list[str],
) -> INoteReadRepository:
    """Semantic search in `collection`, degrading to `files` (one notice) when vectra fails."""
    return FallbackNoteReadRepositoryAdapter(
        VectraNoteReadRepositoryAdapter(client=client, collection=collection, files=files),
        files,
        on_fallback=lambda _error: notices.append(VECTRA_FALLBACK_NOTICE),
        fails_with=(NoteStorageError,),
    )


def build_manifest_provider(vault: Path | None) -> YamlManifestProviderAdapter:
    """The manifest loader: the packaged default merged with `<vault>/noesis.yaml`."""
    return YamlManifestProviderAdapter(vault)


def build_note_mapper() -> NoteMapper:
    """The mapper between notes and Markdown, with its frontmatter codec."""
    return NoteMapper(YamlFrontmatterCodecAdapter())


def with_declared_sources(
    primary: INoteReadRepository,
    manifest: Manifest,
    vault: Path | None,
    mapper: NoteMapper,
    client: VectraCliClient | None = None,
    notices: list[str] | None = None,
) -> INoteReadRepository:
    """`primary` alone, or merged with the manifest's other sources.

    The primary keeps following the environment (`NOESIS_SEARCH_BACKEND`). Every other source
    is one more `INoteReadRepository`, whatever its role: a `filesystem` or `obsidian` source
    reads its `path` (relative to the vault) as files; a `vector` source is the vectra
    collection named after the source, indexing that same `path`, and degrades to its files
    when vectra cannot answer. Without a vault, or without a `client` for a `vector` source,
    the source is skipped. Their rankings are fused, primary first.
    """
    readers: list[SourceReader] = [SourceReader(manifest.primary(), primary)]
    for spec in manifest.sources:
        if spec.role is SourceRoleEnum.PRIMARY or vault is None or not spec.path:
            continue
        files: INoteReadRepository = _file_reader(vault, spec, mapper)
        if spec.type is SourceTypeEnum.VECTOR:
            if client is None:
                continue
            files = _vectra_reader(client, spec.name, files, notices if notices is not None else [])
        readers.append(SourceReader(spec, files))
    if len(readers) == 1:
        return primary
    return MultiSourceNoteReadRepositoryAdapter(readers)


def _file_reader(vault: Path, spec: SourceSpec, mapper: NoteMapper) -> INoteReadRepository:
    folder: Path = Path(spec.path or ".").expanduser()
    return FilesystemNoteReadRepositoryAdapter(
        folder if folder.is_absolute() else vault / folder, mapper
    )


def build_unit_of_work_factory(
    environment: Environment, mapper: NoteMapper, notices: list[str] | None = None
) -> Callable[[], INotesUnitOfWork]:
    """The factory of units of work for `NOESIS_WRITER_BACKEND`.

    `filesystem` writes files under the vault (so it needs one, checked now, before the
    curator spends budget); `mcp` writes through Obsidian's MCP server; `vectra` writes the
    files and then syncs them into `NOESIS_VECTRA_COLLECTION`, appending one notice to
    `notices` when the sync fails (the notes are written all the same).

    Raises:
        VaultNotConfiguredError: The writer is `filesystem` and no vault is configured.
    """
    backend: WriterBackendEnum = environment.notes.writer_backend
    match backend:
        case WriterBackendEnum.FILESYSTEM:
            vault: Path = require_vault(environment)
            return lambda: FilesystemNotesUnitOfWorkAdapter(
                FilesystemNoteRepositoryAdapter(vault, mapper)
            )
        case WriterBackendEnum.MCP:
            client = build_obsidian_mcp_client(environment)
            return lambda: McpNotesUnitOfWorkAdapter(McpNoteRepositoryAdapter(client, mapper))
        case WriterBackendEnum.VECTRA:
            root: Path = require_vault(environment)
            vectra: VectraCliClient = build_vectra_client(environment)
            collection: str = environment.notes.vectra_collection
            sink: list[str] = notices if notices is not None else []
            return lambda: VectraNotesUnitOfWorkAdapter(
                VectraNoteRepositoryAdapter(
                    files=FilesystemNoteRepositoryAdapter(root, mapper),
                    client=vectra,
                    collection=collection,
                    root=root,
                    on_sync_failure=lambda _error: sink.append(VECTRA_SYNC_NOTICE),
                )
            )
        case _ as unhandled:
            assert_never(unhandled)


def build_apply(environment: Environment) -> ApplyCurationHandler:
    """Wire the apply handler: storage and the failure log, never the curator or the queue.

    Args:
        environment: Loaded settings.

    Returns:
        The handler behind `noesis notes apply`.
    """
    vault: Path | None = require_vault(environment) if needs_vault(environment) else None
    mapper: NoteMapper = build_note_mapper()
    clock = SystemClockAdapter()
    return ApplyCurationHandler(
        uow_factory=build_unit_of_work_factory(environment, mapper),
        clock=clock,
        policy=AutoCurationPolicy(),
        manifest=build_manifest_provider(vault),
        ids=UlidNoteIdGeneratorAdapter(clock),
        read_repository=build_read_repository(environment, vault, mapper, []),
        failures=JsonFileApplyFailureLogAdapter(
            environment.runtime.state_dir.joinpath(*APPLY_FAILED_FOLDER)
        ),
    )


def build_notes(environment: Environment, *, curator: ICurator | None = None) -> NotesHandlers:
    """Wire the Notes handlers for `environment`.

    Args:
        environment: Loaded settings.
        curator: Curator to use instead of the Claude CLI adapter (tests, other providers).

    Returns:
        The wired handlers.
    """
    vault: Path | None = require_vault(environment) if needs_vault(environment) else None
    mapper: NoteMapper = build_note_mapper()
    notices: list[str] = []
    clock = SystemClockAdapter()
    manifest: YamlManifestProviderAdapter = build_manifest_provider(vault)
    read_repository: INoteReadRepository = with_declared_sources(
        build_read_repository(environment, vault, mapper, notices),
        manifest.load_now(),
        vault,
        mapper,
        build_vectra_client(environment),
        notices,
    )
    queue = JsonFileParkedCurationQueueAdapter(
        environment.runtime.state_dir.joinpath(*PARKED_FOLDER)
    )

    curate = CurateWorkBriefHandler(
        apply=ApplyCurationHandler(
            uow_factory=build_unit_of_work_factory(environment, mapper, notices),
            clock=clock,
            policy=AutoCurationPolicy(),
            manifest=manifest,
            ids=UlidNoteIdGeneratorAdapter(clock),
            read_repository=read_repository,
        ),
        read_repository=read_repository,
        manifest=manifest,
        curator=curator or build_curator(environment),
        queue=queue,
        clock=SystemClockAdapter(),
        retry_delay_seconds=environment.curator.retry_seconds,
    )
    return NotesHandlers(
        curate=curate,
        retry=RetryParkedCurationHandler(queue=queue, curate=curate),
        search=SearchNotesHandler(read_repository=read_repository),
        recall=RecallNotesHandler(
            read_repository=read_repository,
            manifest=manifest,
            clock=clock,
            agent=_LazyRecallAgent(lambda: build_recall_agent(environment)),
            max_input_chars=environment.recall.max_input_chars,
        ),
        list_notes=ListNotesHandler(read_repository=read_repository),
        list_parked=ListParkedCurationsHandler(queue=queue),
        notices=notices,
    )
