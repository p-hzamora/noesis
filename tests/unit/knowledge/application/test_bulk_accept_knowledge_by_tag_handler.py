"""BulkAcceptKnowledgeByTagHandler (FR-019, FR-020; AC-025..AC-027, AC-029; bulk edge cases)."""

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import USER, bulk_command
from tests.support.review_fakes import (
    CountingSchema,
    FakeReviewQueueReadRepository,
    RecordingUowFactory,
    ReviewEnv,
    make_review_env,
    seed_assertion,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import (
    BulkAcceptResultDto,
    TaggedProposalDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    Tag,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    GraphStoreUnavailableError,
    ReviewNotAuthorisedError,
    StatusConflictError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit

TAG = "origin:migrated"
PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
RETRACTED = RecordStatusEnum.RETRACTED


def review_entries(env: ReviewEnv) -> dict[tuple[str, str], object]:
    return {k: v for k, v in env.store.ledger.items() if v.command.startswith("review.")}


async def bulk_fixture(env: ReviewEnv) -> dict[str, RecordId]:
    """K1 (acme, revised to head 2), K2 (global), K3 (accepted) tagged; K5 untagged."""
    k1 = await seed_knowledge(env, "k1", project="acme", tags=(TAG,))
    await env.base.revise_knowledge.handle(revise_command(k1))
    k2 = await seed_knowledge(env, "k2", tags=(TAG,))
    k3 = await seed_knowledge(env, "k3", tags=(TAG,), status=ACCEPTED)
    k5 = await seed_knowledge(env, "k5", project="acme")
    return {"k1": k1, "k2": k2, "k3": k3, "k5": k5}


def sample_of(result: BulkAcceptResultDto) -> list[tuple[str, str | None, int]]:
    return [(s.id, s.project_key, s.head_revision) for s in result.sample]


@pytest.mark.parametrize("actor", [USER, AGENT], ids=["user", "agent"])
async def test_preview_counts_and_lists_a_sample_for_any_actor_and_writes_nothing(
    actor: Actor,
) -> None:
    """AC-025."""
    env = await make_review_env()
    records = await bulk_fixture(env)
    commits, ledger = env.store.commits, dict(env.store.ledger)

    result = await env.bulk_accept().handle(bulk_command(actor=actor, apply=False))

    assert isinstance(result, BulkAcceptResultDto)
    assert (result.applied, result.tag, result.basis) == (False, TAG, "migration")
    assert (result.matched, result.proposed, result.skipped_not_proposed) == (3, 2, 1)
    assert (result.accepted, result.skipped_changed) == (0, 0)
    assert sample_of(result) == [
        (records["k1"].value, "acme", 2),
        (records["k2"].value, None, 1),
    ]
    assert all(s.title and s.subtype for s in result.sample)
    assert env.store.commits == commits
    assert env.store.ledger == ledger
    assert env.queue_read.page_calls == [(None, 10)]


async def test_preview_sample_is_the_ten_lowest_ids_of_twelve() -> None:
    env = await make_review_env()
    ids = [await seed_knowledge(env, f"k{i}", tags=(TAG,)) for i in range(12)]

    result = await env.bulk_accept().handle(bulk_command(apply=False))

    assert result.proposed == 12
    assert [s.id for s in result.sample] == [i.value for i in ids[:10]]


async def test_a_tag_that_matches_nothing_gives_zero_everywhere() -> None:
    env = await make_review_env()
    await bulk_fixture(env)

    result = await env.bulk_accept().handle(bulk_command("nothing:here"))

    assert (result.matched, result.proposed, result.skipped_not_proposed) == (0, 0, 0)
    assert (result.accepted, result.skipped_changed, result.sample) == (0, 0, ())


async def test_the_user_accepts_every_proposed_tagged_record_with_basis_migration() -> None:
    """AC-026."""
    env = await make_review_env()
    records = await bulk_fixture(env)
    ledger_before = dict(env.store.ledger)
    factory = RecordingUowFactory(env.store)

    result = await env.bulk_accept(factory).handle(bulk_command())

    assert result.applied is True
    assert (result.matched, result.proposed, result.skipped_not_proposed) == (3, 2, 1)
    assert (result.accepted, result.skipped_changed) == (2, 0)
    assert sample_of(result) == [
        (records["k1"].value, "acme", 2),
        (records["k2"].value, None, 1),
    ]
    for name, pinned in (("k1", 2), ("k2", 1)):
        stored = env.store.knowledge[records[name].value]
        decision = stored.latest_decision
        assert stored.status is ACCEPTED
        assert decision is not None
        assert (decision.seq, decision.transition) == (1, ReviewTransitionEnum.ACCEPT)
        assert (decision.from_status, decision.to_status) == (PROPOSED, ACCEPTED)
        assert (decision.actor, decision.basis) == (USER, DecisionBasisEnum.MIGRATION)
        assert decision.pinned_revision == pinned == stored.head_number
        assert decision.reason == f"bulk accept: tag {TAG}"
        assert len(env.store.decisions[records[name].value]) == 1
    assert env.store.knowledge[records["k3"].value].latest_decision is None
    assert env.store.knowledge[records["k5"].value].status is PROPOSED
    assert env.store.knowledge[records["k5"].value].latest_decision is None
    assert env.store.ledger == ledger_before
    assert factory.commit_log == [[records["k1"].value], [records["k2"].value]]


async def test_a_given_reason_is_stored_on_every_decision() -> None:
    env = await make_review_env()
    records = await bulk_fixture(env)

    await env.bulk_accept().handle(bulk_command(reason="vault import reviewed"))

    for name in ("k1", "k2"):
        decision = env.store.knowledge[records[name].value].latest_decision
        assert decision is not None
        assert decision.reason == "vault import reviewed"


async def test_a_second_run_accepts_nothing() -> None:
    env = await make_review_env()
    await bulk_fixture(env)
    await env.bulk_accept().handle(bulk_command())
    factory = RecordingUowFactory(env.store)

    result = await env.bulk_accept(factory).handle(bulk_command())

    assert (result.accepted, result.proposed, result.skipped_not_proposed) == (0, 0, 3)
    assert factory.commit_log == []


async def test_only_knowledge_that_is_proposed_and_carries_the_exact_tag_is_written() -> None:
    env = await make_review_env()
    target = await seed_knowledge(env, "k1", tags=(TAG,))
    lookalike = await seed_knowledge(env, "k2", tags=("origin:migrated-old",))
    retracted = await seed_knowledge(env, "k3", tags=(TAG,), status=RETRACTED)
    tagged_assertion = await seed_assertion(
        env,
        AssertionPredicateEnum.SUPPORTS,
        target,
        lookalike,
    )
    env.store.assertions[tagged_assertion.value].applicability = Applicability(
        tags=frozenset({Tag(value=TAG)})
    )

    result = await env.bulk_accept().handle(bulk_command())

    assert (result.matched, result.proposed, result.accepted) == (2, 1, 1)
    assert env.store.knowledge[target.value].status is ACCEPTED
    assert env.store.knowledge[lookalike.value].status is PROPOSED
    assert env.store.knowledge[retracted.value].latest_decision is None
    assert env.store.assertions[tagged_assertion.value].status is PROPOSED
    assert env.store.assertions[tagged_assertion.value].latest_decision is None


async def test_the_agent_is_refused_before_any_store_is_touched() -> None:
    """AC-027."""
    env = await make_review_env()
    await bulk_fixture(env)
    factory = RecordingUowFactory(env.store)
    schema = CountingSchema(env.schema)
    reader = FakeReviewQueueReadRepository(env.store)

    handler = env.bulk_accept(factory, schema=schema, queue_reader=reader)
    with pytest.raises(ReviewNotAuthorisedError) as raised:
        await handler.handle(bulk_command(actor=AGENT))

    assert raised.value.metadata["reason"] == "bulk_accept_requires_user"
    assert factory.opened == 0
    assert reader.calls == 0
    assert schema.calls == 0


async def test_applying_needs_the_review_schema_step() -> None:
    env = await make_review_env(steps=("core",))

    with pytest.raises(StoreNotInitialisedError) as raised:
        await env.bulk_accept().handle(bulk_command())

    assert raised.value.metadata["missing_steps"] == ["review"]


async def test_two_hundred_fifty_records_are_read_in_pages_of_one_hundred_and_accepted_in_order() -> (
    None
):
    """Bulk paging edge case."""
    env = await make_review_env()
    ids = [await seed_knowledge(env, f"k{i:03}", tags=(TAG,)) for i in range(250)]
    factory = RecordingUowFactory(env.store)

    result = await env.bulk_accept(factory).handle(bulk_command())

    assert env.queue_read.page_calls == [
        (None, 100),
        (ids[99], 100),
        (ids[199], 100),
        (ids[249], 100),
    ]
    assert (result.matched, result.proposed, result.accepted) == (250, 250, 250)
    assert [s.id for s in result.sample] == [i.value for i in ids[:10]]
    assert factory.commit_log == [[i.value] for i in ids]


async def test_records_changed_before_their_turn_are_skipped_and_counted() -> None:
    """R2 is retracted and R3 loses the tag after the page was read."""
    env = await make_review_env()
    r1 = await seed_knowledge(env, "r1", tags=(TAG,))
    r2 = await seed_knowledge(env, "r2", tags=(TAG,))
    r3 = await seed_knowledge(env, "r3", tags=(TAG,))

    async def change_after_the_page(page: list[TaggedProposalDto]) -> None:
        assert [p.id for p in page] == [r1.value, r2.value, r3.value]
        env.store.knowledge[r2.value].status = RETRACTED
        env.store.knowledge[r3.value].applicability = Applicability()

    env.queue_read.after_page = change_after_the_page

    result = await env.bulk_accept().handle(bulk_command())

    assert (result.accepted, result.skipped_changed) == (1, 2)
    assert env.store.knowledge[r1.value].status is ACCEPTED
    assert env.store.knowledge[r2.value].latest_decision is None
    assert env.store.knowledge[r3.value].latest_decision is None
    assert env.store.knowledge[r3.value].status is PROPOSED


async def test_a_record_revised_before_its_turn_is_accepted_at_the_new_head() -> None:
    env = await make_review_env()
    record = await seed_knowledge(env, "seed", tags=(TAG,))

    async def revise_after_the_page(page: list[TaggedProposalDto]) -> None:
        await env.base.revise_knowledge.handle(revise_command(record))

    env.queue_read.after_page = revise_after_the_page

    result = await env.bulk_accept().handle(bulk_command())

    decision = env.store.knowledge[record.value].latest_decision
    assert result.accepted == 1
    assert decision is not None
    assert decision.pinned_revision == 2 == env.store.knowledge[record.value].head_number


async def test_losing_a_decision_race_counts_as_skipped_changed_and_the_run_continues() -> None:
    env = await make_review_env()
    r1 = await seed_knowledge(env, "r1", tags=(TAG,))
    r2 = await seed_knowledge(env, "r2", tags=(TAG,))
    factory = RecordingUowFactory(
        env.store, fail_on_commit=1, error=StatusConflictError("lost", {"record_id": r1.value})
    )

    result = await env.bulk_accept(factory).handle(bulk_command())

    assert (result.accepted, result.skipped_changed) == (1, 1)
    assert env.store.knowledge[r1.value].status is PROPOSED
    assert env.store.knowledge[r2.value].status is ACCEPTED


async def test_a_crash_midway_keeps_committed_records_and_a_rerun_resumes() -> None:
    """AC-029."""
    env = await make_review_env()
    r = [await seed_knowledge(env, f"r{i}", tags=(TAG,)) for i in range(1, 6)]
    crashing = RecordingUowFactory(env.store, fail_on_commit=3)

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await env.bulk_accept(crashing).handle(bulk_command())

    assert raised.value.metadata["accepted_before_failure"] == 2
    assert raised.value.metadata["last_accepted_id"] == r[1].value
    assert (
        "Rerun the same command; records already accepted are skipped." in raised.value.next_steps
    )
    assert [env.store.knowledge[i.value].status for i in r] == [
        ACCEPTED,
        ACCEPTED,
        PROPOSED,
        PROPOSED,
        PROPOSED,
    ]
    assert env.store.knowledge[r[2].value].latest_decision is None

    resumed = await env.bulk_accept().handle(bulk_command())

    assert (resumed.accepted, resumed.matched, resumed.proposed) == (3, 5, 3)
    assert resumed.skipped_not_proposed == 2
    assert [len(env.store.decisions[i.value]) for i in r] == [1, 1, 1, 1, 1]

    factory = RecordingUowFactory(env.store)
    finished = await env.bulk_accept(factory).handle(bulk_command())
    assert (finished.accepted, finished.proposed, finished.skipped_not_proposed) == (0, 0, 5)
    assert factory.commit_log == []


async def test_a_failure_on_the_first_record_reports_zero_accepted_and_no_last_id() -> None:
    env = await make_review_env()
    await seed_knowledge(env, "r1", tags=(TAG,))

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await env.bulk_accept(RecordingUowFactory(env.store, fail_on_commit=1)).handle(
            bulk_command()
        )

    assert raised.value.metadata["accepted_before_failure"] == 0
    assert raised.value.metadata["last_accepted_id"] is None
