"""Curating a work brief: storing, skipping, retrying and parking."""

import pytest
from tests.support.notes_support import (
    FixedClock,
    InMemoryNoteReadRepository,
    InMemoryNoteRepository,
    InMemoryNotesUnitOfWork,
    InMemoryParkedQueue,
    ScriptedCurator,
    a_brief,
    a_decision,
    a_draft,
    a_note,
)

from noesis.bounded_context.notes.application.dtos import CurationResultDto, NoteSummaryDto
from noesis.bounded_context.notes.application.handlers.commands import (
    ApplyCurationHandler,
    CurateWorkBriefCommand,
    CurateWorkBriefHandler,
    RetryParkedCurationCommand,
    RetryParkedCurationHandler,
)
from noesis.bounded_context.notes.application.mappers import WorkBriefMapper
from noesis.bounded_context.notes.domain.policies import AutoCurationPolicy
from noesis.bounded_context.notes.domain.value_objects import CurationActionEnum, NoteOriginEnum
from noesis.exceptions import (
    CurationFailedError,
    NoteStorageError,
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
        self.units: list[InMemoryNotesUnitOfWork] = []
        self.commit_errors: list[NoteStorageError] = []

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        def unit_of_work() -> InMemoryNotesUnitOfWork:
            self.units.append(InMemoryNotesUnitOfWork(self.repository, self.commit_errors))
            return self.units[-1]

        self.handler = CurateWorkBriefHandler(
            apply=ApplyCurationHandler(
                uow_factory=unit_of_work, clock=FixedClock(), policy=AutoCurationPolicy()
            ),
            read_repository=self.read_repository,
            curator=curator,
            queue=self.queue,
            clock=FixedClock(),
            retry_delay_seconds=7.0,
            sleep=sleep,
        )


def _command(
    max_attempts: int = 2, park: bool = True, dry_run: bool = False
) -> CurateWorkBriefCommand:
    return CurateWorkBriefCommand(
        brief=a_brief(), max_attempts=max_attempts, park_on_failure=park, dry_run=dry_run
    )


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
    assert "noesis notes retry ticket-1" in raised.value.next_steps[0]
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


def _storage_error() -> NoteStorageError:
    return NoteStorageError(
        "Wrote 1 of 2 note(s) through the Obsidian MCP before it failed: disk full",
        {
            "backend": "mcp",
            "written": ["repos/demo/auto/decisions/a.md"],
            "not_written": ["repos/demo/auto/decisions/b.md"],
        },
        next_steps=["Check NOESIS_OBSIDIAN_MCP_URL (`noesis doctor`)."],
    )


@pytest.mark.parametrize("failing_step", ["lookup", "commit"])
async def test_storage_failure_parks_the_brief_and_keeps_the_error_details(
    failing_step: str,
) -> None:
    world = _World(ScriptedCurator((a_decision(),)))
    if failing_step == "lookup":
        world.repository.get_errors.append(_storage_error())
    else:
        world.commit_errors.append(_storage_error())

    with pytest.raises(CurationFailedError) as raised:
        await world.handler.handle(_command())

    error: CurationFailedError = raised.value
    assert error.error_code == "NOTES_201_CURATION_FAILED"
    assert error.message.startswith("Storing the notes failed: Wrote 1 of 2 note(s)")
    assert error.metadata == {
        "backend": "mcp",
        "written": ["repos/demo/auto/decisions/a.md"],
        "not_written": ["repos/demo/auto/decisions/b.md"],
        "repository": "demo",
        "ticket": "ticket-1",
    }
    assert error.next_steps == (
        "Check NOESIS_OBSIDIAN_MCP_URL (`noesis doctor`).",
        "Fix the cause, then run `noesis notes retry ticket-1`.",
    )
    assert world.queue.parked["ticket-1"][0] == a_brief()
    assert isinstance(error.__cause__, NoteStorageError)
    assert world.repository.stored == {}


async def test_storage_failure_without_parking_propagates() -> None:
    world = _World(ScriptedCurator((a_decision(),)))
    world.commit_errors.append(_storage_error())

    with pytest.raises(NoteStorageError) as raised:
        await world.handler.handle(_command(park=False))

    assert raised.value.error_code == "NOTES_102_NOTE_STORAGE_FAILED"
    assert world.queue.parked == {}


async def test_retry_that_hits_a_storage_failure_keeps_the_ticket_then_succeeds() -> None:
    world = _World(ScriptedCurator((a_decision(),), (a_decision(),), (a_decision(),)))
    retry = RetryParkedCurationHandler(queue=world.queue, curate=world.handler)
    world.commit_errors.extend([_storage_error(), _storage_error()])
    with pytest.raises(CurationFailedError):
        await world.handler.handle(_command())

    with pytest.raises(CurationFailedError) as raised:
        await retry.handle(RetryParkedCurationCommand(ticket="ticket-1"))

    assert raised.value.metadata["ticket"] == "ticket-1"
    assert raised.value.metadata["written"] == ["repos/demo/auto/decisions/a.md"]
    assert raised.value.next_steps[-1].endswith("`noesis notes retry ticket-1` again.")
    assert list(world.queue.parked) == ["ticket-1"]  # kept, and not parked a second time

    result: CurationResultDto = await retry.handle(RetryParkedCurationCommand(ticket="ticket-1"))
    assert len(result.created) == 1
    assert world.queue.parked == {}


async def test_a_dry_run_judges_and_reports_but_stores_nothing() -> None:
    world = _World(ScriptedCurator((a_decision(),)))

    result: CurationResultDto = await world.handler.handle(_command(dry_run=True))

    assert result.created == ("repos/demo/auto/decisions/use-ttl-cache.md",)
    assert world.curator.calls == 1
    assert world.repository.stored == {}
    assert world.units[0].commits == 0
    assert world.queue.parked == {}


async def test_a_dry_run_never_parks_a_failed_judgement() -> None:
    world = _World(ScriptedCurator("boom", "still broken"))

    with pytest.raises(CurationFailedError) as raised:
        await world.handler.handle(_command(dry_run=True))

    assert world.queue.parked == {}
    assert "ticket" not in raised.value.metadata
    assert raised.value.next_steps == ()


async def test_a_dry_run_does_not_park_when_reading_existing_notes_fails() -> None:
    world = _World(ScriptedCurator((a_decision(),)))
    world.repository.get_errors.append(NoteStorageError("vault unreadable"))

    with pytest.raises(NoteStorageError):
        await world.handler.handle(_command(dry_run=True))

    assert world.queue.parked == {}
