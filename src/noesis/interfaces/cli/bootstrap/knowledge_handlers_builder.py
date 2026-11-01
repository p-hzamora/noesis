"""Wires the Knowledge context's handlers."""

from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.knowledge.application.handlers.commands import (
    CurateWorkBriefHandler,
    RetryParkedCurationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries import (
    ListNotesHandler,
    ListParkedCurationsHandler,
    SearchNotesHandler,
)
from noesis.bounded_context.knowledge.application.ports.curation import ICurator
from noesis.bounded_context.knowledge.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.domain.services import AutoCurationPolicy
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
    default_system_prompt,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.queue import (
    JsonFileParkedCurationQueueAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage import (
    FallbackNoteReadRepositoryAdapter,
    FilesystemKnowledgeUnitOfWorkAdapter,
    FilesystemNoteReadRepositoryAdapter,
    FilesystemNoteRepositoryAdapter,
    ObsidianMcpNoteReadRepositoryAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.core import Environment, SearchBackendEnum
from noesis.exceptions import CuratorPromptUnreadableError, VaultNotConfiguredError
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

PARKED_FOLDER: tuple[str, ...] = ("knowledge", "parked")
MCP_FALLBACK_NOTICE: str = "Obsidian MCP unreachable, searched files instead"


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeHandlers:
    """The Knowledge context's inbound actions, wired.

    Attributes:
        curate: Curate a work brief.
        retry: Retry a parked curation.
        search: Free-text note search.
        list_notes: List notes.
        list_parked: List parked curations.
        notices: Messages the adapters raised while the handlers ran (e.g. the search fell
            back to files); the commands show them. Empty on the default backend.
    """

    curate: CurateWorkBriefHandler
    retry: RetryParkedCurationHandler
    search: SearchNotesHandler
    list_notes: ListNotesHandler
    list_parked: ListParkedCurationsHandler
    notices: list[str]


def require_vault(environment: Environment) -> Path:
    """The configured vault folder.

    Raises:
        VaultNotConfiguredError: `NOESIS_VAULT_DIR` is not set.
    """
    vault: Path | None = environment.knowledge.vault_dir
    if vault is None:
        raise VaultNotConfiguredError(
            "No vault folder is configured.",
            {"setting": "NOESIS_VAULT_DIR"},
            next_steps=["Run `noesis config init --vault-dir <folder>` or set NOESIS_VAULT_DIR."],
        )
    return vault


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


def build_read_repository(
    environment: Environment, vault: Path, mapper: NoteMapper, notices: list[str]
) -> INoteReadRepository:
    """The note read repository for `NOESIS_SEARCH_BACKEND`.

    `filesystem` (default) never touches the network. `obsidian-mcp` searches through Obsidian
    and degrades to the filesystem, appending one notice to `notices`, when it is unreachable.
    The same repository serves `knowledge search`, `knowledge list` and the curator's
    related-notes lookup, so curation never fails because Obsidian is closed.
    """
    files: FilesystemNoteReadRepositoryAdapter = FilesystemNoteReadRepositoryAdapter(vault, mapper)
    settings = environment.knowledge
    if settings.search_backend is not SearchBackendEnum.OBSIDIAN_MCP:
        return files
    token: str | None = (
        settings.obsidian_mcp_token.get_secret_value() if settings.obsidian_mcp_token else None
    )
    client: ObsidianMcpClient = ObsidianMcpClient(
        settings.obsidian_mcp_url,
        token=token,
        timeout_seconds=settings.obsidian_mcp_timeout_seconds,
    )
    return FallbackNoteReadRepositoryAdapter(
        ObsidianMcpNoteReadRepositoryAdapter(client, mapper, listing=files),
        files,
        on_fallback=lambda _error: notices.append(MCP_FALLBACK_NOTICE),
    )


def build_knowledge(
    environment: Environment, *, curator: ICurator | None = None
) -> KnowledgeHandlers:
    """Wire the Knowledge handlers for `environment`.

    Args:
        environment: Loaded settings.
        curator: Curator to use instead of the Claude CLI adapter (tests, other providers).

    Returns:
        The wired handlers.
    """
    vault: Path = require_vault(environment)
    mapper: NoteMapper = NoteMapper()
    notices: list[str] = []
    read_repository: INoteReadRepository = build_read_repository(
        environment, vault, mapper, notices
    )
    queue: JsonFileParkedCurationQueueAdapter = JsonFileParkedCurationQueueAdapter(
        environment.runtime.state_dir.joinpath(*PARKED_FOLDER)
    )

    def unit_of_work() -> IKnowledgeUnitOfWork:
        return FilesystemKnowledgeUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(vault, mapper))

    curate: CurateWorkBriefHandler = CurateWorkBriefHandler(
        uow_factory=unit_of_work,
        read_repository=read_repository,
        curator=curator or build_curator(environment),
        queue=queue,
        clock=SystemClockAdapter(),
        policy=AutoCurationPolicy(),
        retry_delay_seconds=environment.curator.retry_seconds,
    )
    return KnowledgeHandlers(
        curate=curate,
        retry=RetryParkedCurationHandler(queue=queue, curate=curate),
        search=SearchNotesHandler(read_repository=read_repository),
        list_notes=ListNotesHandler(read_repository=read_repository),
        list_parked=ListParkedCurationsHandler(queue=queue),
        notices=notices,
    )
