"""Curate one work brief: ask the curator, apply the auto-curation policy, store the notes."""

import asyncio
from collections.abc import Awaitable, Callable

from noesis.bounded_context.notes.application.dtos import (
    CurationResultDto,
    NoteSearchResultDto,
    NoteSummaryDto,
)
from noesis.bounded_context.notes.application.mappers import WorkBriefMapper
from noesis.bounded_context.notes.application.ports.curation import ICurator
from noesis.bounded_context.notes.application.ports.queue import IParkedCurationQueue
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import CurationDecision, WorkBrief
from noesis.exceptions import (
    CurationFailedError,
    CuratorFailedError,
    NoteStorageError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.utils import FrozenObject

from .apply_curation_handler import ApplyCurationCommand, ApplyCurationHandler

RELATED_NOTES_LIMIT: int = 8

type Sleeper = Callable[[float], Awaitable[None]]


class CurateWorkBriefCommand(FrozenObject):
    """Curate `brief`.

    Attributes:
        brief: The finished work.
        max_attempts: Curator runs before giving up (2 = one automatic retry).
        park_on_failure: Whether to park the brief for a manual retry when every attempt fails.
    """

    brief: WorkBriefContract
    max_attempts: int
    park_on_failure: bool


class CurateWorkBriefHandler(IHandler[CurateWorkBriefCommand, CurationResultDto]):
    """Turns a work brief into stored auto notes, retrying the curator and parking on failure."""

    def __init__(
        self,
        *,
        apply: ApplyCurationHandler,
        read_repository: INoteReadRepository,
        curator: ICurator,
        queue: IParkedCurationQueue,
        clock: IClock,
        retry_delay_seconds: float,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._apply: ApplyCurationHandler = apply
        self._read_repository: INoteReadRepository = read_repository
        self._curator: ICurator = curator
        self._queue: IParkedCurationQueue = queue
        self._clock: IClock = clock
        self._retry_delay_seconds: float = retry_delay_seconds
        self._sleep: Sleeper = sleep

    async def handle(self, action: CurateWorkBriefCommand) -> CurationResultDto:
        """Curate the brief and store what is admitted.

        Raises:
            CurationFailedError: Every curator attempt failed, or the notes could not be stored
                (the brief is parked when asked).
            NoteStorageError: The notes could not be stored and parking is off.
        """
        brief: WorkBrief = WorkBriefMapper.to_domain(action.brief)
        found: NoteSearchResultDto = await self._read_repository.search(
            brief.search_text(), area=brief.area, limit=RELATED_NOTES_LIMIT
        )
        related: list[NoteSummaryDto] = list(found.notes)
        decisions: tuple[CurationDecision, ...] = await self._curate(action, brief, related)
        try:
            return await self._apply.handle(
                ApplyCurationCommand(
                    area=brief.area,
                    decisions=decisions,
                    commits=brief.commit_shas(),
                    session=brief.short_session(),
                )
            )
        except NoteStorageError as error:
            if not action.park_on_failure:
                raise
            ticket: str = await self._queue.park(
                action.brief, error=error.message, now=self._clock.now()
            )
            raise CurationFailedError(
                f"Storing the notes failed: {error.message}",
                {**error.metadata, "repository": action.brief.repository, "ticket": ticket},
                next_steps=[
                    *error.next_steps,
                    f"Fix the cause, then run `noesis notes retry {ticket}`.",
                ],
            ) from error

    async def _curate(
        self, action: CurateWorkBriefCommand, brief: WorkBrief, related: list[NoteSummaryDto]
    ) -> tuple[CurationDecision, ...]:
        """Run the curator, retrying after a pause; park and raise when it keeps failing.

        The queue parks the published contract, not `brief`: a retry re-enters through the
        command, so the parked payload must stay the versioned contract.
        """
        last_error: CuratorFailedError | None = None
        for attempt in range(1, action.max_attempts + 1):
            try:
                return await self._curator.curate(brief, related)
            except CuratorFailedError as error:
                last_error = error
                if attempt < action.max_attempts:
                    await self._sleep(self._retry_delay_seconds)
        reason: str = last_error.message if last_error else "the curator was never run"
        if not action.park_on_failure:
            raise CurationFailedError(
                f"Curation failed: {reason}", {"repository": action.brief.repository}
            )
        ticket: str = await self._queue.park(action.brief, error=reason, now=self._clock.now())
        raise CurationFailedError(
            f"Curation failed after {action.max_attempts} attempt(s): {reason}",
            {"repository": action.brief.repository, "ticket": ticket},
            next_steps=[f"Fix the cause, then run `noesis notes retry {ticket}`."],
        ) from last_error
