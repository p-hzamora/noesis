"""List the parked curation tickets. Reads only the inbox, so it works with the store down."""

from noesis.bounded_context.knowledge.application.dtos import ParkedCurationDto
from noesis.bounded_context.knowledge.application.ports.curation import (
    CurationTicket,
    ICurationInbox,
)
from noesis.bounded_context.knowledge.domain.value_objects import CurationStageEnum
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class ListParkedCurationsQuery(FrozenObject):
    """List every parked ticket."""


class ListParkedCurationsHandler(IHandler[ListParkedCurationsQuery, tuple[ParkedCurationDto, ...]]):
    """Every failed ticket, oldest failure first."""

    def __init__(self, *, inbox: ICurationInbox, clock: IClock) -> None:
        self._inbox: ICurationInbox = inbox
        self._clock: IClock = clock

    async def handle(self, action: ListParkedCurationsQuery) -> tuple[ParkedCurationDto, ...]:
        """The parked tickets with the stage a retry returns to and why they failed.

        Raises:
            CurationInboxFailedError: The inbox cannot be read.
        """
        now = self._clock.now()
        parked: list[ParkedCurationDto] = []
        for ticket in await self._inbox.list_parked():
            at = ticket.parked_at or ticket.updated_at
            parked.append(_dto(ticket, at.isoformat(), max(0, int((now - at).total_seconds()))))
        return tuple(parked)


def _dto(ticket: CurationTicket, parked_at: str, age_seconds: int) -> ParkedCurationDto:
    progress = ticket.progress
    return ParkedCurationDto(
        ticket=ticket.ticket,
        stage=(progress.failed_at or CurationStageEnum.STAGED).value,
        reason=progress.reason.value if progress.reason is not None else "unknown",
        repository=ticket.submission.project_key,
        parked_at=parked_at,
        age_seconds=age_seconds,
    )
