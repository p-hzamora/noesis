"""Wires the Capture context's handlers."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.capture.application.handlers.commands import (
    DisableCaptureHandler,
    EnableCaptureHandler,
    FlushCaptureHandler,
    RecordCommitHandler,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetCaptureStatusHandler,
    ListCaptureRunsHandler,
)
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
from noesis.core import Environment
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

CAPTURE_FOLDER: str = "capture"
LOCK_TIMEOUT_SECONDS: float = 10.0


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
    clock = SystemClockAdapter()
    mapper = CaptureSessionMapper()
    journal = JsonlCaptureJournalAdapter(root / "journal")
    recorder = CaptureJournalRecorder(journal=journal, clock=clock, trace=environment.capture.trace)
    vcs = GitCliVcsReaderAdapter()
    files = BriefFiles(root / "briefs")

    def unit_of_work(session_id: SessionId) -> ICaptureUnitOfWork:
        return JsonFileCaptureUnitOfWorkAdapter(
            JsonFileCaptureSessionRepositoryAdapter(root / "sessions", mapper),
            session_id,
            lock_timeout_seconds=LOCK_TIMEOUT_SECONDS,
        )

    publishers = WorkBriefPublisherResolver(
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
