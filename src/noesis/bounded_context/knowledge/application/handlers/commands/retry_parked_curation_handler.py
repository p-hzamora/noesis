"""Retry a parked curation once, in the foreground."""

from noesis.bounded_context.knowledge.application.dtos import CurationResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.curate_work_brief_handler import (
    CurateWorkBriefCommand,
    CurateWorkBriefHandler,
)
from noesis.bounded_context.knowledge.application.ports.queue import IParkedCurationQueue
from noesis.exceptions import (
    CurationFailedError,
    ParkedCurationNotFoundError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.utils import FrozenObject


class RetryParkedCurationCommand(FrozenObject):
    """Retry the parked brief behind `ticket`.

    Attributes:
        ticket: Ticket printed when the brief was parked.
    """

    ticket: str


class RetryParkedCurationHandler(IHandler[RetryParkedCurationCommand, CurationResultDto]):
    """Runs curation once for a parked brief and removes it from the queue on success."""

    def __init__(self, *, queue: IParkedCurationQueue, curate: CurateWorkBriefHandler) -> None:
        self._queue: IParkedCurationQueue = queue
        self._curate: CurateWorkBriefHandler = curate

    async def handle(self, action: RetryParkedCurationCommand) -> CurationResultDto:
        """Curate the parked brief; it stays parked if this attempt fails too.

        Raises:
            ParkedCurationNotFoundError: No parked brief has this ticket.
            CurationFailedError: The attempt failed.
        """
        brief: WorkBriefContract | None = await self._queue.get(action.ticket)
        if brief is None:
            raise ParkedCurationNotFoundError(
                f"No parked curation with ticket {action.ticket!r}.",
                {"ticket": action.ticket},
                next_steps=["Run `noesis knowledge parked` to list tickets."],
            )
        try:
            result: CurationResultDto = await self._curate.handle(
                CurateWorkBriefCommand(brief=brief, max_attempts=1, park_on_failure=False)
            )
        except CurationFailedError as error:
            raise CurationFailedError(
                error.message,
                {**error.metadata, "ticket": action.ticket},
                next_steps=[
                    f"Fix the cause, then run `noesis knowledge retry {action.ticket}` again."
                ],
            ) from error
        await self._queue.discard(action.ticket)
        return result
