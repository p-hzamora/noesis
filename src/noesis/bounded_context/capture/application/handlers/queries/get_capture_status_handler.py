"""Show the state of a capture session."""

from noesis.bounded_context.capture.application.assemblers import CaptureSessionAssembler
from noesis.bounded_context.capture.application.dtos import CaptureStatusDto
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class GetCaptureStatusQuery(FrozenObject):
    """Status of one session.

    Attributes:
        session_id: The agent session.
    """

    session_id: str


class GetCaptureStatusHandler(IHandler[GetCaptureStatusQuery, CaptureStatusDto]):
    """Reads the session (a missing one is reported as switched off)."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory

    async def handle(self, action: GetCaptureStatusQuery) -> CaptureStatusDto:
        """The session's status."""
        session_id = SessionId(value=action.session_id)
        async with self._uow_factory(session_id) as uow:
            session: CaptureSession | None = await uow.sessions.get(session_id)
        return CaptureSessionAssembler.to_dto(session, session_id)
