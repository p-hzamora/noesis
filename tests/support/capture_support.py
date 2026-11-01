"""In-memory fakes of the Capture ports, and builders."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from noesis.bounded_context.capture.application.dtos import (
    AgentHookPlanDto,
    AgentHooksDto,
    CaptureRunDto,
    PublicationDto,
    TranscriptSnapshotDto,
)
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.application.ports.publishing import IWorkBriefPublisher
from noesis.bounded_context.capture.application.ports.transcript import ITranscriptReader
from noesis.bounded_context.capture.application.ports.uow import ICaptureUnitOfWork
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.repositories import ICaptureSessionRepository
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, DiffSize, SessionId
from noesis.shared_kernel.contracts import WorkBriefContract

START: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
SESSION: str = "session-1"
REPO: Path = Path("/work/demo")


def a_commit(
    sha: str = "a" * 40, *, files: int = 2, lines: int = 25, subject: str = "feat: x"
) -> CommitRecord:
    """A commit of the given size."""
    return CommitRecord(sha=sha, subject=subject, size=DiffSize(files=files, lines=lines))


class InMemoryCaptureSessionRepository(ICaptureSessionRepository):
    """Sessions in a dict, staged until the unit of work commits."""

    def __init__(self) -> None:
        self.stored: dict[str, CaptureSession] = {}
        self.staged: dict[str, CaptureSession] = {}

    async def get(self, session_id: SessionId) -> CaptureSession | None:
        return self.staged.get(session_id.value) or self.stored.get(session_id.value)

    async def save(self, session: CaptureSession) -> None:
        self.staged[session.id.value] = session


class InMemoryCaptureUnitOfWork(ICaptureUnitOfWork):
    """Publishes staged sessions on commit; counts commits."""

    def __init__(self, repository: InMemoryCaptureSessionRepository) -> None:
        self._repository: InMemoryCaptureSessionRepository = repository
        self.commits: int = 0

    @property
    def sessions(self) -> ICaptureSessionRepository:
        return self._repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()

    async def commit(self) -> None:
        self._repository.stored.update(self._repository.staged)
        self._repository.staged.clear()
        self.commits += 1

    async def rollback(self) -> None:
        self._repository.staged.clear()


class FakeVcs(IVcsReader):
    """A repository whose HEAD the test sets."""

    def __init__(self, head: CommitRecord | None = None, root: Path | None = REPO) -> None:
        self.head: CommitRecord | None = head or a_commit()
        self.root: Path | None = root

    async def repository_root(self, cwd: Path) -> Path | None:
        return self.root

    async def head_commit(self, root: Path) -> CommitRecord | None:
        return self.head

    async def branch(self, root: Path) -> str:
        return "main"

    async def stat_lines(self, root: Path, shas: Sequence[str], *, limit: int) -> list[str]:
        return [f"{sha[:8]} | 3 +++" for sha in shas][:limit]


class FakeTranscripts(ITranscriptReader):
    """Returns a preset snapshot (None = unreadable) and records the offsets asked for."""

    def __init__(self, snapshot: TranscriptSnapshotDto | None = None) -> None:
        self.snapshot: TranscriptSnapshotDto | None = snapshot or TranscriptSnapshotDto(
            end_offset=100,
            has_real_work=True,
            goal="speed up login",
            excerpt="A: chose a TTL cache",
        )
        self.offsets: list[int] = []

    async def read(self, path: Path | None, *, since_offset: int) -> TranscriptSnapshotDto | None:
        self.offsets.append(since_offset)
        return self.snapshot


class RecordingPublisher(IWorkBriefPublisher):
    """Keeps published briefs; can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail: bool = fail
        self.briefs: list[WorkBriefContract] = []

    async def publish(self, brief: WorkBriefContract) -> PublicationDto:
        if self.fail:
            return PublicationDto(published=False, detail="cannot start")
        self.briefs.append(brief)
        return PublicationDto(published=True, reference=f"/briefs/{len(self.briefs)}.json")


class InMemoryJournal(ICaptureJournal):
    """Journal entries per session."""

    def __init__(self) -> None:
        self.entries: dict[str, list[CaptureRunDto]] = {}

    async def append(self, session_id: SessionId, entry: CaptureRunDto) -> None:
        self.entries.setdefault(session_id.value, []).append(entry)

    async def read(self, session_id: SessionId) -> list[CaptureRunDto]:
        return list(self.entries.get(session_id.value, []))

    def outcomes(self, session_id: str = SESSION) -> list[str]:
        return [entry.outcome for entry in self.entries.get(session_id, [])]


class InMemoryAgentHookRegistry(IAgentHookRegistry):
    """A registry that records what was planned and applied; `changed` is scripted."""

    def __init__(self, *, changed: bool = True, backup: str | None = "/tmp/settings.bak") -> None:  # noqa: S108
        self.changed: bool = changed
        self.backup: str | None = backup
        self.planned: list[str | None] = []
        self.applied: list[AgentHookPlanDto] = []

    async def status(self) -> AgentHooksDto:
        return AgentHooksDto(
            settings_file="/s.json", installed={"Stop": ["noesis hook claude-code"]},
            missing_events=["SessionEnd"],
        )  # fmt: skip

    async def plan(self, command: str | None) -> AgentHookPlanDto:
        self.planned.append(command)
        return AgentHookPlanDto(
            settings_file="/s.json",
            command=command,
            changed=self.changed,
            diff="diff" if self.changed else "",
            after_text="{}\n",
            installed_before={"Stop": ["old"]},
            installed_after={"Stop": [command]} if command else {},
        )

    async def apply(self, plan: AgentHookPlanDto) -> str | None:
        self.applied.append(plan)
        return self.backup
