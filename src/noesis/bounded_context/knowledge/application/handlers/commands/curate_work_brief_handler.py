"""Curate one work brief: ask the curator, apply the auto-curation policy, store the notes."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from noesis.bounded_context.knowledge.application.dtos import (
    CurationResultDto,
    NoteSearchResultDto,
    NoteSummaryDto,
    SkippedCandidateDto,
)
from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper
from noesis.bounded_context.knowledge.application.ports.curation import ICurator
from noesis.bounded_context.knowledge.application.ports.queue import IParkedCurationQueue
from noesis.bounded_context.knowledge.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.policies import (
    AutoCurationPolicy,
    CurationOutcome,
    CurationOutcomeEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationDecision,
    NoteArea,
    NoteLocation,
    NoteOriginEnum,
    WorkBrief,
)
from noesis.exceptions import (
    CurationFailedError,
    CuratorFailedError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.utils import FrozenObject

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
        uow_factory: Callable[[], IKnowledgeUnitOfWork],
        read_repository: INoteReadRepository,
        curator: ICurator,
        queue: IParkedCurationQueue,
        clock: IClock,
        policy: AutoCurationPolicy,
        retry_delay_seconds: float,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._uow_factory: Callable[[], IKnowledgeUnitOfWork] = uow_factory
        self._read_repository: INoteReadRepository = read_repository
        self._curator: ICurator = curator
        self._queue: IParkedCurationQueue = queue
        self._clock: IClock = clock
        self._policy: AutoCurationPolicy = policy
        self._retry_delay_seconds: float = retry_delay_seconds
        self._sleep: Sleeper = sleep

    async def handle(self, action: CurateWorkBriefCommand) -> CurationResultDto:
        """Curate the brief and store what is admitted.

        Raises:
            CurationFailedError: Every curator attempt failed (the brief is parked when asked).
        """
        brief: WorkBrief = WorkBriefMapper.to_domain(action.brief)
        found: NoteSearchResultDto = await self._read_repository.search(
            brief.search_text(), area=brief.area, limit=RELATED_NOTES_LIMIT
        )
        related: list[NoteSummaryDto] = list(found.notes)
        decisions: tuple[CurationDecision, ...] = await self._curate(action, brief, related)
        outcomes: list[CurationOutcome] = await self._store(brief, decisions)
        return CurationResultDto(
            repository=brief.repository,
            created=_paths(outcomes, CurationOutcomeEnum.CREATED),
            updated=_paths(outcomes, CurationOutcomeEnum.UPDATED),
            skipped=tuple(
                SkippedCandidateDto(candidate=outcome.candidate, reason=outcome.reason)
                for outcome in outcomes
                if outcome.outcome is CurationOutcomeEnum.SKIPPED
            ),
        )

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
            next_steps=[f"Fix the cause, then run `noesis knowledge retry {ticket}`."],
        ) from last_error

    async def _store(
        self, brief: WorkBrief, decisions: tuple[CurationDecision, ...]
    ) -> list[CurationOutcome]:
        """Apply the policy to every decision and commit the resulting notes together."""
        now: datetime = self._clock.now()
        area: NoteArea = brief.area
        commits: tuple[str, ...] = brief.commit_shas()
        session: str = brief.short_session()
        outcomes: list[CurationOutcome] = []
        async with self._uow_factory() as uow:
            for decision in decisions:
                existing_auto: Note | None = None
                existing_manual: Note | None = None
                if decision.draft is not None:
                    location = NoteLocation(
                        area=area,
                        origin=NoteOriginEnum.AUTO,
                        kind=decision.draft.kind,
                        slug=decision.draft.slug,
                    )
                    existing_auto = await uow.notes.get(location)
                    existing_manual = await uow.notes.get(
                        location.with_origin(NoteOriginEnum.MANUAL)
                    )
                outcome: CurationOutcome = self._policy.apply(
                    decision,
                    area=area,
                    existing_auto=existing_auto,
                    existing_manual=existing_manual,
                    commits=commits,
                    session=session,
                    now=now,
                )
                if outcome.note is not None:
                    await uow.notes.save(outcome.note)
                outcomes.append(outcome)
            await uow.commit()
        return outcomes


def _paths(outcomes: list[CurationOutcome], kind: CurationOutcomeEnum) -> tuple[str, ...]:
    """Paths of the notes behind outcomes of one kind."""
    return tuple(
        o.note.location.relative_path for o in outcomes if o.outcome is kind and o.note is not None
    )
