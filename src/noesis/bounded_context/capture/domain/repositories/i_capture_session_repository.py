"""Write repository of the CaptureSession aggregate."""

import abc

from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import SessionId


class ICaptureSessionRepository(abc.ABC):
    """Loads and stores capture sessions by id."""

    @abc.abstractmethod
    async def get(self, session_id: SessionId) -> CaptureSession | None:
        """The session, or None when it was never switched on."""
        ...

    @abc.abstractmethod
    async def save(self, session: CaptureSession) -> None:
        """Stage the session; it becomes durable when the unit of work commits."""
        ...
