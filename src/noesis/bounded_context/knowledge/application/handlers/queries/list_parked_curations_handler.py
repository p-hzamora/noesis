"""List briefs waiting for a manual retry."""

from noesis.bounded_context.knowledge.application.dtos import ParkedCurationListDto
from noesis.bounded_context.knowledge.application.ports.queue import IParkedCurationQueue
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListParkedCurationsQuery(FrozenObject):
    """List every parked curation."""


class ListParkedCurationsHandler(IHandler[ListParkedCurationsQuery, ParkedCurationListDto]):
    """Reads the parked-curation queue."""

    def __init__(self, *, queue: IParkedCurationQueue) -> None:
        self._queue: IParkedCurationQueue = queue

    async def handle(self, action: ListParkedCurationsQuery) -> ParkedCurationListDto:
        """Every parked brief, oldest first."""
        return ParkedCurationListDto(parked=tuple(await self._queue.list_parked()))
