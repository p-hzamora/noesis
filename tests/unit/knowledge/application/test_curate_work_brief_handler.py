"""Curating a work brief: storing, skipping, retrying and parking."""

import pytest
from tests.support.knowledge_support import (
    FixedClock,
    InMemoryKnowledgeUnitOfWork,
    InMemoryNoteReadRepository,
    InMemoryNoteRepository,
    InMemoryParkedQueue,
    ScriptedCurator,
    a_brief,
    a_decision,
    a_draft,
    a_note,
)

from noesis.bounded_context.knowledge.application.dtos import CurationResultDto, NoteSummaryDto
from noesis.bounded_context.knowledge.application.handlers.commands import (
    CurateWorkBriefCommand,
    CurateWorkBriefHandler,
    RetryParkedCurationCommand,
    RetryParkedCurationHandler,
)
from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper
from noesis.bounded_context.knowledge.domain.policies import AutoCurationPolicy
from noesis.bounded_context.knowledge.domain.value_objects import CurationActionEnum, NoteOriginEnum
from noesis.exceptions import (
    CurationFailedError,
    ParkedCurationNotFoundError,
)

pytestmark = pytest.mark.unit


class _World:
    def __init__(
        self, curator: ScriptedCurator, related: list[NoteSummaryDto] | None = None
    ) -> None:
        self.repository = InMemoryNoteRepository()
        self.read_repository = InMemoryNoteReadRepository(related or [])
        self.queue = InMemoryParkedQueue()
        self.curator = curator
        self.sleeps: list[float] = []
        self.units: list[InMemoryKnowledgeUnitOfWork] = []

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        def unit_of_work() -> InMemoryKnowledgeUnitOfWork:
            self.units.append(InMemoryKnowledgeUnitOfWork(self.repository))
            return self.units[-1]

        self.handler = CurateWorkBriefHandler(
            uow_factory=unit_of_work,
            read_repository=self.read_repository,
            curator=curator,
            queue=self.queue,
            clock=FixedClock(),
            policy=AutoCurationPolicy(),
            retry_delay_seconds=7.0,
            sleep=sleep,
        )


def _command(max_attempts: int = 2, park: bool = True) -> CurateWorkBriefCommand:
    return CurateWorkBriefCommand(brief=a_brief(), max_attempts=max_attempts, park_on_failure=park)


async def test_admitted_decisions_are_stored_and_skips_reported() -> None:
    world = _World(
        ScriptedCurator(
            (
                a_decision(),
                a_decision(action=CurationActionEnum.SKIP, candidate="readme typo"),
            )
        )
    )

    result: CurationResultDto = await world.handler.handle(_command())

    assert result.created == ("repos/demo/auto/decisions/use-ttl-cache.md",)
    assert [(s.candidate, s.reason) for s in result.skipped] == [
        ("readme typo", "single instance, no shared state")
    ]
    stored = world.repository.stored["repos/demo/auto/decisions/use-ttl-cache.md"]
    assert stored.commits == ("8e6d3b5fe598c6bf",)
    assert stored.session == "abcd1234"
    assert world.units[0].commits == 1


async def test_related_notes_are_searched_with_goal_and_commit_subjects_and_shown_to_the_curator() -> (
    None
):
    related = [
        NoteSummaryDto(
            path="repos/demo/decisions/x.md",
            title="x",
            kind="decision",
            origin="manual",
            updated=None,
            snippet="",
        )
    ]
    world = _World(ScriptedCurator(()), related)

    await world.handler.handle(_command())

    assert world.read_repository.queries == ["make login faster feat: add TTL cache"]
    assert world.curator.related_seen == [related]
    assert world.curator.briefs_seen == [WorkBriefMapper.to_domain(a_brief())]


async def test_existing_auto_notes_are_updated_and_manual_ones_protected() -> None:
    world = _World(
        ScriptedCurator(
            (
                a_decision(),
                a_decision(draft=a_draft(slug="manual-topic"), candidate="manual"),
            )
        )
    )
    world.repository.stored["repos/demo/auto/decisions/use-ttl-cache.md"] = a_note()
    world.repository.stored["repos/demo/decisions/manual-topic.md"] = a_note(
        origin=NoteOriginEnum.MANUAL, slug="manual-topic"
    )

    result: CurationResultDto = await world.handler.handle(_command())

    assert result.updated == ("repos/demo/auto/decisions/use-ttl-cache.md",)
    assert result.skipped[0].reason == "covered by repos/demo/decisions/manual-topic.md"


async def test_a_failed_curator_run_is_retried_once_after_the_delay() -> None:
    world = _World(ScriptedCurator("boom", (a_decision(),)))

    result: CurationResultDto = await world.handler.handle(_command())

    assert world.curator.calls == 2
    assert world.sleeps == [7.0]
    assert len(result.created) == 1


async def test_repeated_failure_parks_the_brief_and_names_the_ticket() -> None:
    world = _World(ScriptedCurator("boom", "still broken"))

    with pytest.raises(CurationFailedError) as raised:
        await world.handler.handle(_command())

    assert raised.value.metadata["ticket"] == "ticket-1"
    assert "noesis knowledge retry ticket-1" in raised.value.next_steps[0]
    assert world.queue.parked["ticket-1"][1] == "still broken"
    assert world.units == []  # nothing was opened, nothing written


async def test_failure_without_parking_raises_without_a_ticket() -> None:
    world = _World(ScriptedCurator("boom"))

    with pytest.raises(CurationFailedError) as raised:
        await world.handler.handle(_command(max_attempts=1, park=False))

    assert "ticket" not in raised.value.metadata
    assert world.queue.parked == {}


async def test_retrying_a_parked_brief_discards_it_on_success_and_keeps_it_on_failure() -> None:
    world = _World(ScriptedCurator("down", "down", "still down", (a_decision(),)))
    retry = RetryParkedCurationHandler(queue=world.queue, curate=world.handler)
    with pytest.raises(CurationFailedError):
        await world.handler.handle(_command())

    with pytest.raises(CurationFailedError) as raised:
        await retry.handle(RetryParkedCurationCommand(ticket="ticket-1"))
    assert raised.value.metadata["ticket"] == "ticket-1"
    assert "ticket-1" in world.queue.parked

    result: CurationResultDto = await retry.handle(RetryParkedCurationCommand(ticket="ticket-1"))
    assert len(result.created) == 1
    assert world.queue.parked == {}


async def test_retrying_an_unknown_ticket_fails_clearly() -> None:
    world = _World(ScriptedCurator())

    with pytest.raises(ParkedCurationNotFoundError):
        await RetryParkedCurationHandler(queue=world.queue, curate=world.handler).handle(
            RetryParkedCurationCommand(ticket="nope")
        )
