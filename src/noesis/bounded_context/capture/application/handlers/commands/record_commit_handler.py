"""Record a finished commit as pending work (the PostToolUse path: no transcript)."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeDto,
    CaptureOutcomeEnum,
    RepositoryLocationDto,
)
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.ports.registry import IRepoRegistry
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.specifications import (
    HeadCandidate,
    NewCommitCandidateSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import (
    CommitRecord,
    RepoId,
    SessionId,
    WorktreeHead,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class RecordCommitCommand(FrozenObject):
    """A git commit just finished in the session.

    Attributes:
        session_id: The (already resolved) session id.
        cwd: Working directory of the session.
        worktree_hint: Worktree the commit command named (`cd <dir> && git commit`), when the
            delivery layer could tell. Only a tiebreaker between several candidate worktrees.
    """

    session_id: str
    cwd: Path
    worktree_hint: Path | None = None


class RecordCommitHandler(IHandler[RecordCommitCommand, CaptureOutcomeDto]):
    """Finds the worktree that just committed and adds its HEAD to the session's pending work.

    Every worktree of the repository is compared with the HEADs the session saw last time and
    with a recency window. One candidate is recorded; several are narrowed by the hint, and
    when that still leaves several nothing is recorded (`ambiguous_worktree`) rather than a
    guess. A candidate that was not recorded stays a candidate at the next hook.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        vcs: IVcsReader,
        clock: IClock,
        recorder: CaptureJournalRecorder,
        registry: IRepoRegistry,
        candidates: NewCommitCandidateSpecification,
    ) -> None:
        self._registry: IRepoRegistry = registry
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._vcs: IVcsReader = vcs
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder
        self._candidates: NewCommitCandidateSpecification = candidates

    async def handle(self, action: RecordCommitCommand) -> CaptureOutcomeDto:
        """Mark the commit, or say why not."""
        session_id = SessionId(value=action.session_id)
        return await self._recorder.record(await self._record(session_id, action))

    async def _record(
        self, session_id: SessionId, action: RecordCommitCommand
    ) -> CaptureOutcomeDto:
        async with self._uow_factory(session_id) as uow:
            session: CaptureSession | None = await uow.sessions.get(session_id)
            if session is None or not session.enabled:
                return _outcome(session_id, CaptureOutcomeEnum.NOT_OPTED_IN)
            location: RepositoryLocationDto | None = await self._vcs.common_dir(action.cwd)
            if location is None:
                return _outcome(session_id, CaptureOutcomeEnum.NOT_IN_REPO, str(action.cwd))
            await self._registry.register(
                RepoId.derive(location.name, str(location.common_dir)), location.root
            )
            heads: list[WorktreeHead] = await self._vcs.worktrees(location.common_dir)
            now = self._clock.now()
            candidates: list[WorktreeHead] = [
                head
                for head in heads
                if self._candidates.is_satisfied_by(
                    HeadCandidate(
                        head=head, baseline_sha=session.observed_heads.get(head.path), now=now
                    )
                )
            ]
            chosen: list[WorktreeHead] = _narrow(candidates, action.worktree_hint)
            recorded: WorktreeHead | None = None
            if len(chosen) == 1:
                result, recorded = await self._add(session, session_id, location, chosen[0])
            elif chosen:
                result = _outcome(
                    session_id, CaptureOutcomeEnum.AMBIGUOUS_WORKTREE, _describe(chosen)
                )
            else:
                result = _outcome(
                    session_id, CaptureOutcomeEnum.NO_NEW_COMMIT, f"{len(heads)} worktree(s)"
                )
            unrecorded: list[WorktreeHead] = [head for head in candidates if head != recorded]
            moved: bool = session.observe_heads(_baseline(session, heads, unrecorded), now=now)
            if moved or recorded is not None:
                await uow.sessions.save(session)
                await uow.commit()
        return result

    async def _add(
        self,
        session: CaptureSession,
        session_id: SessionId,
        location: RepositoryLocationDto,
        head: WorktreeHead,
    ) -> tuple[CaptureOutcomeDto, WorktreeHead | None]:
        """Record `head`'s commit in the (unsaved) session; the head is None when nothing was read."""
        commit: CommitRecord | None = await self._vcs.head_commit(Path(head.path))
        if commit is None:
            return _outcome(session_id, CaptureOutcomeEnum.NOT_IN_REPO, head.path), None
        repo: RepoId = RepoId.derive(location.name, str(location.common_dir))
        added: bool = session.record_commit(
            commit.committed_in(worktree=head.path, branch=head.branch),
            repository_path=str(location.root),
            repo_id=repo.value,
            now=self._clock.now(),
        )
        kind = CaptureOutcomeEnum.MARKED if added else CaptureOutcomeEnum.ALREADY_PENDING
        return _outcome(session_id, kind, f"{commit.sha[:8]} {commit.subject}"), head


def _outcome(
    session_id: SessionId, kind: CaptureOutcomeEnum, detail: str = ""
) -> CaptureOutcomeDto:
    return CaptureOutcomeDto(session_id=session_id.value, outcome=kind, detail=detail)


def _narrow(candidates: list[WorktreeHead], hint: Path | None) -> list[WorktreeHead]:
    """The candidates the hint points into, when that settles a choice between several."""
    if len(candidates) < 2 or hint is None:
        return candidates
    named: list[WorktreeHead] = [
        head for head in candidates if hint == Path(head.path) or Path(head.path) in hint.parents
    ]
    return named if len(named) == 1 else candidates


def _baseline(
    session: CaptureSession, heads: list[WorktreeHead], unrecorded: list[WorktreeHead]
) -> dict[str, str]:
    """HEADs to remember: every current worktree, except that an unrecorded candidate keeps the
    HEAD seen before (or none), so it is still a candidate next time (the baseline never
    advances past a commit that was not recorded). Worktrees that are gone drop out."""
    held: set[str] = {head.path for head in unrecorded}
    baseline: dict[str, str] = {}
    for head in heads:
        if head.path not in held:
            baseline[head.path] = head.sha
        elif head.path in session.observed_heads:
            baseline[head.path] = session.observed_heads[head.path]
    return baseline


def _describe(candidates: list[WorktreeHead]) -> str:
    return ", ".join(f"{head.path} ({head.sha[:8]})" for head in candidates)
