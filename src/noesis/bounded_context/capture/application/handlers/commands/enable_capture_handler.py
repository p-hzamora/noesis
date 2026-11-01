"""Switch capture on for a session."""

from noesis.bounded_context.capture.application.assemblers import CaptureSessionAssembler
from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeDto,
    CaptureOutcomeEnum,
    CaptureStatusDto,
)
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class EnableCaptureCommand(FrozenObject):
    """Switch capture on.

    Attributes:
        session_id: The agent session.
        mode: `live` hands briefs to the curator; `dry-run` only records them.
    """

    session_id: str
    mode: CaptureModeEnum


class EnableCaptureHandler(IHandler[EnableCaptureCommand, CaptureStatusDto]):
    """Creates the session if needed and switches it on."""

    def __init__(
        self, *, uow_factory: UnitOfWorkFactory, clock: IClock, recorder: CaptureJournalRecorder
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder

    async def handle(self, action: EnableCaptureCommand) -> CaptureStatusDto:
        """Switch capture on and return the new status."""
        session_id: SessionId = SessionId(value=action.session_id)
        async with self._uow_factory(session_id) as uow:
            session: CaptureSession = await uow.sessions.get(session_id) or CaptureSession.create(
                session_id, now=self._clock.now()
            )
            session.enable(action.mode, now=self._clock.now())
            await uow.sessions.save(session)
            await uow.commit()
        await self._recorder.record(
            CaptureOutcomeDto(
                session_id=session_id.value,
                outcome=CaptureOutcomeEnum.ENABLED,
                detail=action.mode.value,
            )
        )
        return CaptureSessionAssembler.to_dto(session, session_id)
