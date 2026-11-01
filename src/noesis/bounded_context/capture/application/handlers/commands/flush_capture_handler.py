"""Hand pending work over as a work brief when the rules allow (the Stop / SessionEnd path)."""

from datetime import datetime
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeDto,
    CaptureOutcomeEnum,
    PublicationDto,
    TranscriptSnapshotDto,
)
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.ports.publishing import IWorkBriefPublisherFactory
from noesis.bounded_context.capture.application.ports.transcript import ITranscriptReader
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.specifications import (
    FlushCandidate,
    OutsideDebounceSpecification,
    PendingWorkSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import DiffSize, SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import CommitRefContract, WorkBriefContract
from noesis.utils import FrozenObject

MAX_STAT_LINES: int = 15


class FlushCaptureCommand(FrozenObject):
    """The agent finished a turn (or the session ended).

    Attributes:
        session_id: The agent session.
        transcript_path: The session transcript, when the agent provides one.
        final: True at session end: ignore the debounce, never keep trivial or failed work.
    """

    session_id: str
    transcript_path: Path | None
    final: bool


class FlushCaptureHandler(IHandler[FlushCaptureCommand, CaptureOutcomeDto]):
    """Checks the rules cheapest first and publishes one brief for all pending commits."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        transcripts: ITranscriptReader,
        vcs: IVcsReader,
        publishers: IWorkBriefPublisherFactory,
        clock: IClock,
        recorder: CaptureJournalRecorder,
        debounce: OutsideDebounceSpecification,
        significance: SignificantChangeSpecification,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._transcripts: ITranscriptReader = transcripts
        self._vcs: IVcsReader = vcs
        self._publishers: IWorkBriefPublisherFactory = publishers
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder
        self._pending: PendingWorkSpecification = PendingWorkSpecification()
        self._debounce: OutsideDebounceSpecification = debounce
        self._significance: SignificantChangeSpecification = significance

    async def handle(self, action: FlushCaptureCommand) -> CaptureOutcomeDto:
        """Hand over, or say which rule held the work back."""
        session_id: SessionId = SessionId(value=action.session_id)
        outcome, reference = await self._flush(session_id, action)
        return await self._recorder.record(outcome, reference=reference)

    async def _flush(
        self, session_id: SessionId, action: FlushCaptureCommand
    ) -> tuple[CaptureOutcomeDto, str | None]:
        def outcome(kind: CaptureOutcomeEnum, detail: str = "") -> CaptureOutcomeDto:
            return CaptureOutcomeDto(session_id=session_id.value, outcome=kind, detail=detail)

        async with self._uow_factory(session_id) as uow:
            session: CaptureSession | None = await uow.sessions.get(session_id)
            if session is None or not session.enabled:
                return outcome(CaptureOutcomeEnum.NOT_OPTED_IN), None
            now: datetime = self._clock.now()
            candidate: FlushCandidate = FlushCandidate(session=session, now=now, final=action.final)
            if not self._pending.is_satisfied_by(candidate):
                return outcome(CaptureOutcomeEnum.NO_PENDING), None
            if not self._debounce.is_satisfied_by(candidate):
                return outcome(CaptureOutcomeEnum.DEBOUNCED, "pending work keeps growing"), None
            if not self._significance.is_satisfied_by(candidate):
                if not action.final:
                    return outcome(CaptureOutcomeEnum.TRIVIAL, _size_detail(session)), None
                session.discard_pending(now=now)
                await uow.sessions.save(session)
                await uow.commit()
                return outcome(CaptureOutcomeEnum.TRIVIAL_DROPPED, _size_detail(session)), None
            snapshot: TranscriptSnapshotDto | None = await self._transcripts.read(
                action.transcript_path, since_offset=session.cursor.offset
            )
            if snapshot is None:
                return outcome(
                    CaptureOutcomeEnum.TRANSCRIPT_UNREADABLE, str(action.transcript_path)
                ), None
            if not snapshot.has_real_work:
                return outcome(CaptureOutcomeEnum.NO_REAL_WORK), None
            brief: WorkBriefContract = await self._brief(session, snapshot)
            publication: PublicationDto = await self._publishers.for_mode(session.mode).publish(
                brief
            )
            if publication.published:
                session.mark_handed_over(transcript_end=snapshot.end_offset, now=now)
                result: CaptureOutcomeDto = outcome(
                    CaptureOutcomeEnum.HANDED_OVER,
                    f"{len(brief.commits)} commit(s), {session.mode.value}",
                )
            else:
                abandoned: bool = session.mark_handover_failed(final=action.final, now=now)
                result = outcome(
                    CaptureOutcomeEnum.HANDOVER_ABANDONED
                    if abandoned
                    else CaptureOutcomeEnum.HANDOVER_FAILED,
                    publication.detail,
                )
            await uow.sessions.save(session)
            await uow.commit()
        return result, publication.reference

    async def _brief(
        self, session: CaptureSession, snapshot: TranscriptSnapshotDto
    ) -> WorkBriefContract:
        """Assemble the work brief of the pending commits."""
        root: Path = Path(session.repository_path or ".")
        shas: list[str] = [commit.sha for commit in session.pending]
        return WorkBriefContract(
            session_id=session.id.value,
            repository=root.name,
            repository_path=str(root),
            branch=await self._vcs.branch(root),
            head=shas[-1],
            commits=tuple(CommitRefContract(sha=c.sha, subject=c.subject) for c in session.pending),
            diff_stat=tuple(await self._vcs.stat_lines(root, shas, limit=MAX_STAT_LINES)),
            goal=snapshot.goal,
            session_excerpt=snapshot.excerpt,
        )


def _size_detail(session: CaptureSession) -> str:
    """`N commit(s), F file(s), L line(s)` for the journal."""
    size: DiffSize = session.pending_size
    return f"{len(session.pending)} commit(s), {size.files} file(s), {size.lines} line(s)"
