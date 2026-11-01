"""Composition root: the only place that chooses concrete adapters and wires handlers.

Commands ask for a context's handlers here; tests can pass replacement adapters through
the keyword arguments instead of patching anything.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import AgentHooksDto
from noesis.bounded_context.capture.application.handlers.commands import (
    DisableCaptureHandler,
    EnableCaptureHandler,
    FlushCaptureHandler,
    InstallAgentHooksHandler,
    RecordCommitHandler,
    UninstallAgentHooksHandler,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetAgentHooksStatusHandler,
    GetAgentHooksStatusQuery,
    GetCaptureStatusHandler,
    ListCaptureRunsHandler,
)
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.bounded_context.capture.application.ports.uow import ICaptureUnitOfWork
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.application.services.publishing import (
    WorkBriefPublisherResolver,
)
from noesis.bounded_context.capture.domain.specifications import (
    OutsideDebounceSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId
from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks import (
    ClaudeCodeSettingsAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.journal import (
    JsonlCaptureJournalAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.persistence import (
    JsonFileCaptureSessionRepositoryAdapter,
    JsonFileCaptureUnitOfWorkAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.persistence.mappers import (
    CaptureSessionMapper,
)
from noesis.bounded_context.capture.infrastructure.outbound.publishing import (
    BriefFiles,
    DetachedProcessWorkBriefPublisherAdapter,
    DryRunWorkBriefPublisherAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.transcript import (
    ClaudeCodeTranscriptReaderAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.vcs import GitCliVcsReaderAdapter
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
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.domain.services import AutoCurationPolicy
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.queue import (
    JsonFileParkedCurationQueueAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage import (
    FilesystemKnowledgeUnitOfWorkAdapter,
    FilesystemNoteReadRepositoryAdapter,
    FilesystemNoteRepositoryAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.core import (
    ClaudeCodeSettings,
    Environment,
)
from noesis.diagnostics.application.dtos import DiagnosticReportDto
from noesis.diagnostics.application.handlers.queries import (
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.infrastructure.outbound.probes import SystemEnvironmentProbeAdapter
from noesis.exceptions import (
    AgentSettingsInvalidError,
    VaultNotConfiguredError,
)
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

PARKED_FOLDER: tuple[str, ...] = ("knowledge", "parked")
CAPTURE_FOLDER: str = "capture"
LOCK_TIMEOUT_SECONDS: float = 10.0


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeHandlers:
    """The Knowledge context's inbound actions, wired.

    Attributes:
        curate: Curate a work brief.
        retry: Retry a parked curation.
        search: Free-text note search.
        list_notes: List notes.
        list_parked: List parked curations.
    """

    curate: CurateWorkBriefHandler
    retry: RetryParkedCurationHandler
    search: SearchNotesHandler
    list_notes: ListNotesHandler
    list_parked: ListParkedCurationsHandler


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
    read_repository: FilesystemNoteReadRepositoryAdapter = FilesystemNoteReadRepositoryAdapter(
        vault, mapper
    )
    queue: JsonFileParkedCurationQueueAdapter = JsonFileParkedCurationQueueAdapter(
        environment.runtime.state_dir.joinpath(*PARKED_FOLDER)
    )

    def unit_of_work() -> IKnowledgeUnitOfWork:
        return FilesystemKnowledgeUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(vault, mapper))

    curate: CurateWorkBriefHandler = CurateWorkBriefHandler(
        uow_factory=unit_of_work,
        read_repository=read_repository,
        curator=curator
        or ClaudeCliCuratorAdapter(
            claude_bin=environment.curator.claude_bin,
            model=environment.curator.model,
            max_budget_usd=environment.curator.max_budget_usd,
            timeout_seconds=environment.curator.timeout_seconds,
        ),
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
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureHandlers:
    """The Capture context's inbound actions, wired.

    Attributes:
        enable: Switch capture on.
        disable: Switch capture off.
        record_commit: Record a finished commit.
        flush: Hand pending work over when ready.
        status: Session status.
        runs: Session journal.
    """

    enable: EnableCaptureHandler
    disable: DisableCaptureHandler
    record_commit: RecordCommitHandler
    flush: FlushCaptureHandler
    status: GetCaptureStatusHandler
    runs: ListCaptureRunsHandler


def curator_command(environment: Environment) -> list[str]:
    """How a detached child re-enters noesis with the same configuration file."""
    return [sys.executable, "-m", "noesis", "--env-file", str(environment.env_file)]


def build_capture(environment: Environment) -> CaptureHandlers:
    """Wire the Capture handlers for `environment`.

    Args:
        environment: Loaded settings.

    Returns:
        The wired handlers.
    """
    root: Path = environment.runtime.state_dir / CAPTURE_FOLDER
    clock: SystemClockAdapter = SystemClockAdapter()
    mapper: CaptureSessionMapper = CaptureSessionMapper()
    journal: JsonlCaptureJournalAdapter = JsonlCaptureJournalAdapter(root / "journal")
    recorder: CaptureJournalRecorder = CaptureJournalRecorder(
        journal=journal, clock=clock, trace=environment.capture.trace
    )
    vcs: GitCliVcsReaderAdapter = GitCliVcsReaderAdapter()
    files: BriefFiles = BriefFiles(root / "briefs")

    def unit_of_work(session_id: SessionId) -> ICaptureUnitOfWork:
        return JsonFileCaptureUnitOfWorkAdapter(
            JsonFileCaptureSessionRepositoryAdapter(root / "sessions", mapper),
            session_id,
            lock_timeout_seconds=LOCK_TIMEOUT_SECONDS,
        )

    publishers: WorkBriefPublisherResolver = WorkBriefPublisherResolver(
        {
            CaptureModeEnum.LIVE: DetachedProcessWorkBriefPublisherAdapter(
                files=files,
                command=curator_command(environment),
                environment=dict(os.environ),
                clock=clock,
            ),
            CaptureModeEnum.DRY_RUN: DryRunWorkBriefPublisherAdapter(files=files, clock=clock),
        }
    )
    return CaptureHandlers(
        enable=EnableCaptureHandler(uow_factory=unit_of_work, clock=clock, recorder=recorder),
        disable=DisableCaptureHandler(uow_factory=unit_of_work, clock=clock, recorder=recorder),
        record_commit=RecordCommitHandler(
            uow_factory=unit_of_work, vcs=vcs, clock=clock, recorder=recorder
        ),
        flush=FlushCaptureHandler(
            uow_factory=unit_of_work,
            transcripts=ClaudeCodeTranscriptReaderAdapter(),
            vcs=vcs,
            publishers=publishers,
            clock=clock,
            recorder=recorder,
            debounce=OutsideDebounceSpecification(environment.capture.debounce_seconds),
            significance=SignificantChangeSpecification(
                min_files=environment.capture.min_files, min_lines=environment.capture.min_lines
            ),
        ),
        status=GetCaptureStatusHandler(uow_factory=unit_of_work),
        runs=ListCaptureRunsHandler(journal=journal),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentHooksHandlers:
    """The agent-hook actions of the Capture context, wired.

    Attributes:
        install: Register the noesis hooks.
        uninstall: Remove the noesis hooks.
        status: Show which hooks are registered.
    """

    install: InstallAgentHooksHandler
    uninstall: UninstallAgentHooksHandler
    status: GetAgentHooksStatusHandler


def build_agent_hooks(
    claude_code: ClaudeCodeSettings, *, settings_file: Path | None = None
) -> AgentHooksHandlers:
    """Wire the agent-hook handlers for Claude Code's settings file.

    Args:
        claude_code: Where Claude Code keeps its settings (names the default file).
        settings_file: Settings file to edit instead of the default (`--settings`).

    Returns:
        The wired handlers.
    """
    registry: IAgentHookRegistry = ClaudeCodeSettingsAdapter(
        (settings_file or claude_code.settings_file).expanduser()
    )
    return AgentHooksHandlers(
        install=InstallAgentHooksHandler(registry=registry),
        uninstall=UninstallAgentHooksHandler(registry=registry),
        status=GetAgentHooksStatusHandler(registry=registry),
    )


async def run_diagnostics(
    environment: Environment, claude_code: ClaudeCodeSettings
) -> DiagnosticReportDto:
    """Gather what diagnostics inspects and run it.

    The installed hook events come from Capture's status query and are handed over as plain
    values, so Diagnostics never sees a Capture type. An unreadable agent settings file is
    reported as a failed check, not as an error.

    Args:
        environment: Loaded settings.
        claude_code: Where Claude Code keeps its settings.

    Returns:
        The diagnostics report.
    """
    settings_file: Path = claude_code.settings_file.expanduser()
    installed_events: tuple[str, ...] | None
    try:
        hooks: AgentHooksDto = await build_agent_hooks(claude_code).status.handle(
            GetAgentHooksStatusQuery()
        )
        installed_events = tuple(hooks.installed)
    except AgentSettingsInvalidError, OSError:
        installed_events = None
    query: RunDiagnosticsQuery = RunDiagnosticsQuery(
        env_file=environment.env_file,
        vault_dir=environment.knowledge.vault_dir,
        state_dir=environment.runtime.state_dir,
        curator_binary=environment.curator.claude_bin,
        hooks_settings_file=settings_file,
        installed_hook_events=installed_events,
    )
    return await RunDiagnosticsHandler(probe=SystemEnvironmentProbeAdapter()).handle(query)
