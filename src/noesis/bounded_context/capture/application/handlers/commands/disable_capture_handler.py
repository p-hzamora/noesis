"""Switch capture off for a session."""

from noesis.bounded_context.capture.application.assemblers import CaptureSessionAssembler
from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeDto,
    CaptureOutcomeEnum,
    CaptureStatusDto,
)
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class DisableCaptureCommand(FrozenObject):
    """Switch capture off.

    Attributes:
        session_id: The agent session.
    """

    session_id: str


class DisableCaptureHandler(IHandler[DisableCaptureCommand, CaptureStatusDto]):
    """Switches the session off; a session that was never on stays absent."""

    def __init__(
        self, *, uow_factory: UnitOfWorkFactory, clock: IClock, recorder: CaptureJournalRecorder
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder

    async def handle(self, action: DisableCaptureCommand) -> CaptureStatusDto:
        """Switch capture off and return the new status."""
        session_id: SessionId = SessionId(value=action.session_id)
        async with self._uow_factory(session_id) as uow:
            session: CaptureSession | None = await uow.sessions.get(session_id)
            if session is not None:
                session.disable(now=self._clock.now())
                await uow.sessions.save(session)
                await uow.commit()
        if session is not None:
            await self._recorder.record(
                CaptureOutcomeDto(session_id=session_id.value, outcome=CaptureOutcomeEnum.DISABLED)
            )
        return CaptureSessionAssembler.to_dto(session, session_id)
