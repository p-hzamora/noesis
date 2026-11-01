"""Record a finished commit as pending work (the PostToolUse path: cheap, no transcript)."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import CaptureOutcomeDto, CaptureOutcomeEnum
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class RecordCommitCommand(FrozenObject):
    """A git commit just finished in the session.

    Attributes:
        session_id: The agent session.
        cwd: Working directory the commit ran in.
    """

    session_id: str
    cwd: Path


class RecordCommitHandler(IHandler[RecordCommitCommand, CaptureOutcomeDto]):
    """Adds HEAD of the working directory's repository to the session's pending work."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        vcs: IVcsReader,
        clock: IClock,
        recorder: CaptureJournalRecorder,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._vcs: IVcsReader = vcs
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder

    async def handle(self, action: RecordCommitCommand) -> CaptureOutcomeDto:
        """Mark the commit, or say why not."""
        session_id = SessionId(value=action.session_id)
        return await self._recorder.record(await self._record(session_id, action.cwd))

    async def _record(self, session_id: SessionId, cwd: Path) -> CaptureOutcomeDto:
        async with self._uow_factory(session_id) as uow:
            session: CaptureSession | None = await uow.sessions.get(session_id)
            if session is None or not session.enabled:
                return CaptureOutcomeDto(
                    session_id=session_id.value, outcome=CaptureOutcomeEnum.NOT_OPTED_IN
                )
            root: Path | None = await self._vcs.repository_root(cwd)
            commit: CommitRecord | None = await self._vcs.head_commit(root) if root else None
            if root is None or commit is None:
                return CaptureOutcomeDto(
                    session_id=session_id.value,
                    outcome=CaptureOutcomeEnum.NOT_IN_REPO,
                    detail=str(cwd),
                )
            added: bool = session.record_commit(
                commit, repository_path=str(root), now=self._clock.now()
            )
            await uow.sessions.save(session)
            await uow.commit()
        return CaptureOutcomeDto(
            session_id=session_id.value,
            outcome=CaptureOutcomeEnum.MARKED if added else CaptureOutcomeEnum.ALREADY_PENDING,
            detail=f"{commit.sha[:8]} {commit.subject}",
        )
