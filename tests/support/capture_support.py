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
    RepositoryLocationDto,
    TranscriptSnapshotDto,
)
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.bounded_context.capture.application.ports.identity import ISessionIdentitySource
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.application.ports.publishing import IWorkBriefPublisher
from noesis.bounded_context.capture.application.ports.read_repositories import (
    ICaptureSessionTreeReader,
)
from noesis.bounded_context.capture.application.ports.registry import IRepoRegistry
from noesis.bounded_context.capture.application.ports.transcript import ITranscriptReader
from noesis.bounded_context.capture.application.ports.uow import ICaptureUnitOfWork
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.repositories import ICaptureSessionRepository
from noesis.bounded_context.capture.domain.value_objects import (
    CommitRecord,
    DiffSize,
    RepoId,
    SessionId,
    WorktreeHead,
)
from noesis.shared_kernel.contracts import WorkBriefContract

START: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
SESSION: str = "session-1"
REPO = Path("/work/demo")


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
    """A repository with worktrees whose HEADs the test sets."""

    def __init__(self) -> None:
        self.location: RepositoryLocationDto | None = RepositoryLocationDto(
            common_dir=REPO / ".git", root=REPO, name="demo"
        )
        self.heads: dict[str, WorktreeHead] = {}
        self.commits: dict[str, CommitRecord] = {}
        self.set_head()

    def set_head(
        self,
        sha: str = "a" * 40,
        *,
        path: Path = REPO,
        branch: str = "main",
        at: datetime = START,
        files: int = 2,
        lines: int = 25,
    ) -> None:
        """Move the HEAD of the worktree at `path` to a commit of the given size."""
        self.heads[str(path)] = WorktreeHead(
            path=str(path), sha=sha, branch=branch, committed_at=at
        )
        self.commits[str(path)] = a_commit(sha, files=files, lines=lines)

    async def common_dir(self, cwd: Path) -> RepositoryLocationDto | None:
        return self.location

    async def worktrees(self, common_dir: Path) -> list[WorktreeHead]:
        return list(self.heads.values())

    async def head_commit(self, root: Path) -> CommitRecord | None:
        return self.commits.get(str(root))

    async def branch(self, root: Path) -> str:
        return "main"

    async def stat_lines(self, root: Path, shas: Sequence[str], *, limit: int) -> list[str]:
        return [f"{sha[:8]} | 3 +++" for sha in shas][:limit]


class FakeIdentitySource(ISessionIdentitySource):
    """An ambient id the test sets and a counter for fresh ones."""

    def __init__(self, ambient: str | None = None) -> None:
        self._ambient: str | None = ambient
        self.fresh_calls: int = 0

    def ambient(self) -> str | None:
        return self._ambient

    def fresh(self) -> str:
        self.fresh_calls += 1
        return f"fresh-{self.fresh_calls}"


class RecordingRepoRegistry(IRepoRegistry):
    """Keeps what was registered, in order."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, Path]] = []

    async def register(self, repo_id: RepoId, path: Path) -> None:
        self.registered.append((repo_id.value, path))


class InMemoryCaptureSessionTreeReader(ICaptureSessionTreeReader):
    """Reads the parent links of the sessions stored in an in-memory repository."""

    def __init__(self, repository: InMemoryCaptureSessionRepository) -> None:
        self._repository: InMemoryCaptureSessionRepository = repository

    async def children_of(self, session_id: SessionId) -> list[SessionId]:
        return [
            session.id
            for session in sorted(self._repository.stored.values(), key=lambda s: s.id.value)
            if session.parent_id == session_id.value
        ]


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
