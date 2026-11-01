"""Show the journal of a capture session."""

from pydantic import Field

from noesis.bounded_context.capture.application.dtos import CaptureRunDto, CaptureRunListDto
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListCaptureRunsQuery(FrozenObject):
    """Journal of one session.

    Attributes:
        session_id: The agent session.
        limit: Most recent entries to return.
    """

    session_id: str
    limit: int = Field(default=50, ge=1, le=1000)


class ListCaptureRunsHandler(IHandler[ListCaptureRunsQuery, CaptureRunListDto]):
    """Reads the session journal, newest `limit` entries in chronological order."""

    def __init__(self, *, journal: ICaptureJournal) -> None:
        self._journal: ICaptureJournal = journal

    async def handle(self, action: ListCaptureRunsQuery) -> CaptureRunListDto:
        """The journal entries."""
        session_id = SessionId(value=action.session_id)
        runs: list[CaptureRunDto] = await self._journal.read(session_id)
        return CaptureRunListDto(session_id=session_id.value, runs=tuple(runs[-action.limit :]))
