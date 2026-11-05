"""Applying decisions: storing, protecting manual notes, dry runs, and keeping failed payloads."""

import pytest
from tests.support.notes_support import (
    FixedClock,
    InMemoryApplyFailureLog,
    InMemoryNoteRepository,
    InMemoryNotesUnitOfWork,
    a_decision,
    a_draft,
    a_note,
)

from noesis.bounded_context.notes.application.dtos import CurationResultDto, RejectedEntryDto
from noesis.bounded_context.notes.application.handlers.commands import (
    ApplyCurationCommand,
    ApplyCurationHandler,
)
from noesis.bounded_context.notes.domain.policies import AutoCurationPolicy
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    NoteArea,
    NoteOriginEnum,
)
from noesis.exceptions import ApplyFailedError, NoteStorageError

pytestmark = pytest.mark.unit

AUTO_PATH = "repos/demo/auto/decisions/use-ttl-cache.md"


class _World:
    def __init__(self, *, with_failure_log: bool = True) -> None:
        self.repository = InMemoryNoteRepository()
        self.failures = InMemoryApplyFailureLog()
        self.units: list[InMemoryNotesUnitOfWork] = []
        self.commit_errors: list[NoteStorageError] = []

        def unit_of_work() -> InMemoryNotesUnitOfWork:
            self.units.append(InMemoryNotesUnitOfWork(self.repository, self.commit_errors))
            return self.units[-1]

        self.handler = ApplyCurationHandler(
            uow_factory=unit_of_work,
            clock=FixedClock(),
            policy=AutoCurationPolicy(),
            failures=self.failures if with_failure_log else None,
        )


def _command(*decisions, **overrides) -> ApplyCurationCommand:  # type: ignore[no-untyped-def]
    fields = {
        "area": NoteArea.for_repository("demo"),
        "decisions": tuple(decisions) or (a_decision(),),
        "raw_payload": '{"decisions": []}',
    }
    return ApplyCurationCommand(**{**fields, **overrides})


async def test_a_draft_is_stored_without_commits_or_session() -> None:
    world = _World()

    result: CurationResultDto = await world.handler.handle(_command())

    assert result.repository == "demo"
    assert result.created == (AUTO_PATH,)
    stored = world.repository.stored[AUTO_PATH]
    assert stored.commits == ()
    assert stored.session is None
    assert world.units[0].commits == 1


async def test_provenance_is_stored_when_given() -> None:
    world = _World()

    await world.handler.handle(_command(commits=("abc123",), session="abcd1234"))

    stored = world.repository.stored[AUTO_PATH]
    assert stored.commits == ("abc123",)
    assert stored.session == "abcd1234"


async def test_an_existing_auto_note_is_updated_not_duplicated() -> None:
    world = _World()
    world.repository.stored[AUTO_PATH] = a_note()

    result = await world.handler.handle(_command())

    assert result.updated == (AUTO_PATH,)
    assert result.created == ()


async def test_a_manual_note_on_the_same_topic_wins() -> None:
    world = _World()
    world.repository.stored["repos/demo/decisions/use-ttl-cache.md"] = a_note(
        origin=NoteOriginEnum.MANUAL
    )

    result = await world.handler.handle(_command())

    assert result.skipped[0].reason == "covered by repos/demo/decisions/use-ttl-cache.md"
    assert AUTO_PATH not in world.repository.stored


async def test_skip_decisions_are_reported_not_stored() -> None:
    world = _World()

    result = await world.handler.handle(
        _command(a_decision(action=CurationActionEnum.SKIP, candidate="typo"))
    )

    assert [s.candidate for s in result.skipped] == ["typo"]
    assert world.repository.stored == {}


async def test_rejected_entries_store_nothing_and_keep_the_payload() -> None:
    world = _World()
    rejected = (RejectedEntryDto(index=1, reason="missing kind or title"),)

    with pytest.raises(ApplyFailedError) as raised:
        await world.handler.handle(
            _command(a_decision(), rejected=rejected, raw_payload="RAW", session="abcd1234")
        )

    assert world.repository.stored == {}
    assert world.units == []
    record = world.failures.records[0]
    assert record["raw_payload"] == "RAW"
    assert record["session"] == "abcd1234"
    assert record["errors"] == ["entry 1: missing kind or title"]
    assert raised.value.metadata["ticket"] == "apply-1"
    assert raised.value.metadata["rejected"] == [{"index": 1, "reason": "missing kind or title"}]
    assert "apply --decisions-file" in raised.value.next_steps[0]


async def test_an_unusable_payload_is_reported_without_an_index() -> None:
    world = _World()
    rejected = (RejectedEntryDto(index=None, reason="not valid JSON"),)

    with pytest.raises(ApplyFailedError):
        await world.handler.handle(_command(rejected=rejected, raw_payload="{oops"))

    assert world.failures.records[0]["errors"] == ["payload: not valid JSON"]
    assert world.failures.records[0]["raw_payload"] == "{oops"


async def test_a_storage_failure_keeps_the_payload_and_lists_what_was_written() -> None:
    world = _World()
    world.commit_errors.append(
        NoteStorageError("disk full", {"written": ["a.md"], "not_written": [AUTO_PATH]})
    )

    with pytest.raises(ApplyFailedError) as raised:
        await world.handler.handle(_command(raw_payload="RAW"))

    assert world.failures.records[0]["raw_payload"] == "RAW"
    assert world.failures.records[0]["errors"] == ["storage: disk full"]
    assert raised.value.metadata["written"] == ["a.md"]
    assert raised.value.metadata["not_written"] == [AUTO_PATH]
    assert raised.value.metadata["ticket"] == "apply-1"


async def test_a_record_that_cannot_be_written_still_hands_back_the_payload() -> None:
    world = _World()
    world.failures.fail_with = NoteStorageError("state dir is read-only")
    rejected = (RejectedEntryDto(index=0, reason="bad"),)

    with pytest.raises(ApplyFailedError) as raised:
        await world.handler.handle(_command(rejected=rejected, raw_payload="RAW"))

    assert raised.value.metadata["raw_payload"] == "RAW"
    assert "ticket" not in raised.value.metadata


async def test_without_a_failure_log_a_storage_failure_propagates_unchanged() -> None:
    world = _World(with_failure_log=False)
    world.commit_errors.append(NoteStorageError("disk full"))

    with pytest.raises(NoteStorageError):
        await world.handler.handle(_command())


async def test_dry_run_reports_paths_but_writes_nothing() -> None:
    world = _World()
    world.repository.stored["repos/demo/decisions/manual-topic.md"] = a_note(
        origin=NoteOriginEnum.MANUAL, slug="manual-topic"
    )

    result = await world.handler.handle(
        _command(
            a_decision(),
            a_decision(draft=a_draft(slug="manual-topic"), candidate="manual"),
            dry_run=True,
        )
    )

    assert result.created == (AUTO_PATH,)
    assert result.skipped[0].reason == "covered by repos/demo/decisions/manual-topic.md"
    assert AUTO_PATH not in world.repository.stored
    assert world.units[0].commits == 0
    assert world.repository.staged == {}


async def test_dry_run_does_not_touch_an_existing_auto_note() -> None:
    world = _World()
    existing = a_note()
    world.repository.stored[AUTO_PATH] = existing
    title, updated_at = existing.title, existing.updated_at

    result = await world.handler.handle(
        _command(a_decision(draft=a_draft(title="A changed title")), dry_run=True)
    )

    assert result.updated == (AUTO_PATH,)
    assert (existing.title, existing.updated_at) == (title, updated_at)
    assert world.repository.stored[AUTO_PATH] is existing


async def test_dry_run_with_rejected_entries_fails_without_a_record() -> None:
    world = _World()
    rejected = (RejectedEntryDto(index=0, reason="bad"),)

    with pytest.raises(ApplyFailedError) as raised:
        await world.handler.handle(_command(rejected=rejected, dry_run=True))

    assert world.failures.records == []
    assert "ticket" not in raised.value.metadata
