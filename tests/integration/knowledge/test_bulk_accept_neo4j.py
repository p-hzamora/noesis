"""The bulk accept by tag over the pinned Neo4j: AC-029, AC-030 and bulk accept against revise."""

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    bulk_command,
)
from tests.support.review_support import (
    MIGRATED,
    CommitFailingFactory,
    ReviewNeo4jEnv,
    count_nodes,
    decisions_of,
    record_snapshot,
    stored_status,
)

from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import AssertionPredicateEnum, Key
from noesis.exceptions import GraphStoreUnavailableError

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac029_bulk_accept_resumes_after_crash(review_env: ReviewNeo4jEnv) -> None:
    """The third unit of work fails to commit; committed records stay, a rerun finishes the rest."""
    settings = review_env.settings
    records = [await review_env.capture(f"r{n}", tags=(MIGRATED,)) for n in range(1, 6)]
    r1, r2, r3, r4, r5 = records
    assert [r.value for r in records] == sorted(r.value for r in records)
    factory = CommitFailingFactory(review_env.uow, fail_on=3)

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await review_env.bulk_accept(factory).handle(bulk_command(MIGRATED))

    assert raised.value.metadata["accepted_before_failure"] == 2
    assert raised.value.metadata["last_accepted_id"] == r2.value
    assert any("Rerun" in step for step in raised.value.next_steps)
    assert [stored_status(settings, r.value) for r in records] == [
        "accepted",
        "accepted",
        "proposed",
        "proposed",
        "proposed",
    ]
    assert decisions_of(settings, r3.value) == []
    assert count_nodes(settings, "Decision") == 2

    resumed = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert (resumed.matched, resumed.proposed, resumed.skipped_not_proposed) == (5, 3, 2)
    assert (resumed.accepted, resumed.skipped_changed) == (3, 0)
    assert all(stored_status(settings, r.value) == "accepted" for r in records)
    for record in (r1, r2, r3, r4, r5):
        assert [d["seq"] for d in decisions_of(settings, record.value)] == [1]

    again = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert (again.accepted, again.proposed, again.skipped_not_proposed) == (0, 0, 5)
    assert count_nodes(settings, "Decision") == 5


async def test_ac030_bulk_accept_touches_only_tagged_proposed_knowledge(
    review_env: ReviewNeo4jEnv,
) -> None:
    settings = review_env.settings
    world = await review_env.seed_selection_world()
    before = {r.value: record_snapshot(settings, r.value) for r in world.untouched}
    k1_before = record_snapshot(settings, world.k1.value)

    result = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert (result.matched, result.proposed, result.accepted) == (3, 1, 1)
    assert (result.skipped_not_proposed, result.skipped_changed) == (2, 0)
    changed = [
        r.value for r in world.untouched if record_snapshot(settings, r.value) != before[r.value]
    ]
    assert changed == []
    after = record_snapshot(settings, world.k1.value)
    assert after != k1_before and after["props"]["status"] == "accepted"
    assert [d["basis"] for d in after["decisions"]] == ["migration"]


async def test_bulk_accept_pins_the_head_when_the_record_was_revised_after_the_preview(
    review_env: ReviewNeo4jEnv,
) -> None:
    record = await review_env.capture("k", tags=(MIGRATED,), project="acme")

    preview = await review_env.bulk_accept().handle(bulk_command(MIGRATED, apply=False))
    await review_env.base.revise_knowledge.handle(revise_command(record, "rv", expected=1))
    applied = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert preview.applied is False and [p.head_revision for p in preview.sample] == [1]
    assert applied.accepted == 1
    assert [p.head_revision for p in applied.sample] == [2]
    (decision,) = decisions_of(review_env.settings, record.value)
    assert decision["pinned_revision"] == 2
    (state,) = await review_env.get_review_states.handle(
        GetReviewStatesQuery(space_key=Key(value="default"), record_ids=(record,))
    )
    assert state.head_revision == 2


async def test_bulk_accept_pages_past_one_hundred_records_in_ascending_order(
    review_env: ReviewNeo4jEnv,
) -> None:
    """The real read adapter honours `after_id`: a page boundary loses and repeats nothing."""
    records = [await review_env.capture(f"r{n:03}", tags=(MIGRATED,)) for n in range(105)]

    result = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert (result.matched, result.proposed, result.accepted) == (105, 105, 105)
    assert all(stored_status(review_env.settings, r.value) == "accepted" for r in records)
    assert count_nodes(review_env.settings, "Decision") == 105


async def test_bulk_accept_does_not_write_a_ledger_entry(review_env: ReviewNeo4jEnv) -> None:
    await review_env.capture("k", tags=(MIGRATED,))
    ledger_before = count_nodes(review_env.settings, "IdempotencyKey")

    await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert count_nodes(review_env.settings, "IdempotencyKey") == ledger_before


async def test_an_accepted_assertion_is_not_selected_even_when_it_carries_the_tag(
    review_env: ReviewNeo4jEnv,
) -> None:
    subject = await review_env.seed_accepted("s")
    object_ = await review_env.seed_accepted("o")
    assertion = await review_env.propose(
        AssertionPredicateEnum.SUPPORTS, subject, object_, "a", tags=(MIGRATED,)
    )
    await review_env.accept_assertion().handle(
        accept_assertion_command(assertion, "a-acc", actor=USER)
    )

    result = await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    assert (result.matched, result.proposed, result.accepted) == (0, 0, 0)
    assert [d["transition"] for d in decisions_of(review_env.settings, assertion.value)] == [
        "accept"
    ]
