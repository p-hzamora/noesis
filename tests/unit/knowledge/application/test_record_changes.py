"""Change-feed production inside Knowledge's handlers (spec 20: change feed, Q-009)."""

from datetime import UTC, datetime

import pytest
from tests.support.knowledge_commands import (
    experience_command,
    knowledge_command,
    racing_factory,
    revise_command,
)
from tests.support.knowledge_support import KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.domain.events import (
    ExperienceRecorded,
    KnowledgeProposed,
    KnowledgeRevised,
    KnowledgeSpaceCreated,
    ProjectRegistered,
    SourceRecorded,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    OwnershipEnum,
    RecordId,
    SourceKindEnum,
)

pytestmark = pytest.mark.unit

KNOWLEDGE_TIME: datetime = datetime(2031, 1, 2, 3, 4, 5, tzinfo=UTC)
RECORD: str = "0" * 25 + "A"
SPACE: str = "0" * 25 + "B"


def test_knowledge_proposed_maps_to_created_with_the_event_revision() -> None:
    event = KnowledgeProposed(
        aggregate_id=RECORD, space_id=SPACE, ownership=OwnershipEnum.GRAPH, revision=1
    )

    changes = pending_changes_from(
        [event], record_type="knowledge", status="proposed", occurred_at=KNOWLEDGE_TIME
    )

    assert len(changes) == 1
    change = changes[0]
    assert (change.space_id, change.record_id) == (SPACE, RECORD)
    assert (change.record_type, change.change_kind) == ("knowledge", "created")
    assert (change.revision, change.status) == (1, "proposed")
    assert change.occurred_at == KNOWLEDGE_TIME != event.occurred_at


def test_knowledge_revised_maps_to_revised_with_the_new_revision() -> None:
    event = KnowledgeRevised(aggregate_id=RECORD, space_id=SPACE, revision=3)

    (change,) = pending_changes_from(
        [event], record_type="knowledge", status="proposed", occurred_at=KNOWLEDGE_TIME
    )

    assert (change.change_kind, change.revision, change.status) == ("revised", 3, "proposed")


def test_experience_recorded_maps_to_created_without_revision_or_status() -> None:
    event = ExperienceRecorded(
        aggregate_id=RECORD, space_id=SPACE, subtype=ExperienceSubtypeEnum.FAILURE
    )

    (change,) = pending_changes_from(
        [event], record_type="experience", status=None, occurred_at=KNOWLEDGE_TIME
    )

    assert (change.record_type, change.change_kind) == ("experience", "created")
    assert (change.revision, change.status) == (None, None)


def test_space_project_and_source_events_map_to_nothing() -> None:
    events = [
        KnowledgeSpaceCreated(aggregate_id=SPACE, key=Key(value="default")),
        ProjectRegistered(aggregate_id=RECORD, space_id=SPACE, key=Key(value="noesis")),
        SourceRecorded(aggregate_id=RECORD, space_id=SPACE, kind=SourceKindEnum.COMMIT),
    ]

    assert (
        pending_changes_from(events, record_type="project", status=None, occurred_at=KNOWLEDGE_TIME)
        == []
    )


def test_events_map_in_order() -> None:
    events = [
        KnowledgeProposed(
            aggregate_id=RECORD, space_id=SPACE, ownership=OwnershipEnum.GRAPH, revision=1
        ),
        KnowledgeRevised(aggregate_id=RECORD, space_id=SPACE, revision=2),
    ]

    changes = pending_changes_from(
        events, record_type="knowledge", status="proposed", occurred_at=KNOWLEDGE_TIME
    )

    assert [(c.change_kind, c.revision) for c in changes] == [("created", 1), ("revised", 2)]


async def test_capture_knowledge_appends_exactly_one_created_change() -> None:
    """The project and source ensure units add records but append nothing (Q-009)."""
    env: KnowledgeEnv = await make_env()

    result = await env.capture_knowledge.handle(knowledge_command())

    assert len(env.store.projects) == 1
    assert len(env.store.sources) == 1
    (change,) = env.store.changes
    assert change.sequence == 1
    assert change.space_id == result.space_id
    assert change.record_id == result.record_id
    assert (change.record_type, change.change_kind) == ("knowledge", "created")
    assert (change.revision, change.status) == (1, "proposed")


async def test_capture_experience_appends_exactly_one_created_change_without_status() -> None:
    env: KnowledgeEnv = await make_env()

    result = await env.capture_experience.handle(experience_command())

    (change,) = env.store.changes
    assert change.record_id == result.record_id
    assert (change.record_type, change.change_kind) == ("experience", "created")
    assert (change.revision, change.status) == (None, None)


async def test_revise_appends_one_revised_change_after_the_created_one() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())

    revised = await env.revise_knowledge.handle(
        revise_command(RecordId(value=captured.record_id), expected=1)
    )

    created, change = env.store.changes
    assert (created.sequence, change.sequence) == (1, 2)
    assert change.record_id == revised.record_id
    assert (change.change_kind, change.revision, change.status) == ("revised", 2, "proposed")


async def test_sequences_are_consecutive_per_space() -> None:
    env: KnowledgeEnv = await make_env()

    await env.capture_knowledge.handle(knowledge_command("k1"))
    await env.capture_experience.handle(experience_command("e1"))
    await env.capture_knowledge.handle(knowledge_command("k2", body="another"))

    assert [c.sequence for c in env.store.changes] == [1, 2, 3]
    assert env.store.change_counters[env.store.changes[0].space_id] == 3


async def test_replays_append_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())
    await env.capture_experience.handle(experience_command())
    revise = revise_command(RecordId(value=captured.record_id), expected=1)
    await env.revise_knowledge.handle(revise)
    before = list(env.store.changes)

    replays = [
        await env.capture_knowledge.handle(knowledge_command()),
        await env.capture_experience.handle(experience_command()),
        await env.revise_knowledge.handle(revise),
    ]

    assert all(result.replayed for result in replays)
    assert env.store.changes == before


async def test_a_capture_that_loses_a_commit_race_leaves_no_change_of_its_own() -> None:
    """The change is staged in the record's unit of work: when that commit fails, it goes too."""
    env: KnowledgeEnv = await make_env()
    command = knowledge_command()

    async def compete() -> None:
        await env.capture_knowledge.handle(command)

    loser = CaptureKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(command)

    assert result.replayed is True
    assert [c.sequence for c in env.store.changes] == [1]
    assert env.store.changes[0].record_id == result.record_id


def _pending(env: KnowledgeEnv) -> PendingRecordChange:
    return PendingRecordChange(
        space_id=SPACE,
        record_id=RECORD,
        record_type="knowledge",
        change_kind="created",
        revision=1,
        status="proposed",
        occurred_at=env.clock.now(),
    )


async def test_a_staged_change_joins_the_store_on_commit_and_is_dropped_on_rollback() -> None:
    env: KnowledgeEnv = await make_env()

    async with env.uow() as rolled_back:
        staged = await rolled_back.changes.append(_pending(env))
        assert staged.sequence == 1
        assert env.store.changes == []
    assert env.store.changes == []

    async with env.uow() as committed:
        again = await committed.changes.append(_pending(env))
        await committed.commit()
    assert again.sequence == 1  # the rolled-back sequence was never consumed
    assert env.store.changes == [again]


async def test_handler_changes_carry_the_handlers_clock_time() -> None:
    env: KnowledgeEnv = await make_env()

    await env.capture_knowledge.handle(knowledge_command())

    (change,) = env.store.changes
    assert change.occurred_at == env.clock.now()
