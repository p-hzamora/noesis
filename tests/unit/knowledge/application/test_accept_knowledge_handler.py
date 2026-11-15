"""AcceptKnowledgeHandler (FR-004..FR-008, FR-015; AC-001, AC-002, AC-008, AC-015; edge cases)."""

import pytest
from tests.support.knowledge_commands import racing_factory, revise_command
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import USER, accept_knowledge_command
from tests.support.review_fakes import (
    ReviewEnv,
    make_review_env,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import AcceptResultDto
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    ExpectedRevisionRequiredError,
    IdempotencyKeyReusedError,
    InvalidStatusTransitionError,
    RecordNotFoundError,
    ReviewNotAuthorisedError,
    RevisionConflictError,
    StatusConflictError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit


def unchanged(env: ReviewEnv, record_id: RecordId, *, status: RecordStatusEnum) -> None:
    record = env.store.knowledge[record_id.value]
    assert record.status is status
    assert record.decision_seq == 0
    assert record.latest_decision is None
    assert not [e for e in env.store.ledger.values() if e.command.startswith("review.")]


async def test_agent_accepts_project_knowledge_and_pins_the_head() -> None:
    """AC-001."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    env.clock.advance(60)

    result = await env.accept_knowledge().handle(accept_knowledge_command(record_id, "a1"))

    assert isinstance(result, AcceptResultDto)
    assert (result.id, result.type, result.status) == (record_id.value, "knowledge", "accepted")
    assert (result.pinned_revision, result.decision_seq) == (1, 1)
    assert (result.basis, result.applied, result.replayed) == ("agent_project", True, False)
    assert result.effects == ()
    assert result.conflicts == ()
    stored = env.store.knowledge[record_id.value]
    assert stored.status is RecordStatusEnum.ACCEPTED
    decision = stored.latest_decision
    assert decision is not None
    assert (decision.seq, decision.transition) == (1, ReviewTransitionEnum.ACCEPT)
    assert (decision.from_status, decision.to_status) == (
        RecordStatusEnum.PROPOSED,
        RecordStatusEnum.ACCEPTED,
    )
    assert decision.actor == AGENT
    assert (decision.pinned_revision, decision.basis) == (1, DecisionBasisEnum.AGENT_PROJECT)
    assert decision.decided_at == env.clock.now()
    ledger = env.store.ledger[(stored.space_id.value, "a1")]
    assert (ledger.command, ledger.record_id) == ("review.accept", record_id)


async def test_user_accepts_global_knowledge_with_basis_user_and_a_reason() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1")

    result = await env.accept_knowledge().handle(
        accept_knowledge_command(record_id, actor=USER, reason="reviewed")
    )

    decision = env.store.knowledge[record_id.value].latest_decision
    assert result.basis == "user"
    assert decision is not None
    assert (decision.actor, decision.reason) == (USER, "reviewed")


async def test_agent_cannot_accept_global_knowledge_and_nothing_is_written() -> None:
    """AC-002."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1")

    with pytest.raises(ReviewNotAuthorisedError):
        await env.accept_knowledge().handle(accept_knowledge_command(record_id))

    unchanged(env, record_id, status=RecordStatusEnum.PROPOSED)


async def test_stale_expected_revision_conflicts_with_both_revisions_and_leaves_it_proposed() -> (
    None
):
    """AC-008."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    await env.base.revise_knowledge.handle(revise_command(record_id))

    with pytest.raises(RevisionConflictError) as raised:
        await env.accept_knowledge().handle(accept_knowledge_command(record_id, expected=1))

    assert raised.value.metadata["expected_revision"] == 1
    assert raised.value.metadata["actual_revision"] == 2
    unchanged(env, record_id, status=RecordStatusEnum.PROPOSED)


async def test_expected_revision_is_required() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")

    with pytest.raises(ExpectedRevisionRequiredError):
        await env.accept_knowledge().handle(accept_knowledge_command(record_id, expected=None))

    unchanged(env, record_id, status=RecordStatusEnum.PROPOSED)


@pytest.mark.parametrize(
    "status",
    [RecordStatusEnum.ACCEPTED, RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED],
)
async def test_accepting_knowledge_that_is_not_proposed_is_an_invalid_transition(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme", status=status)

    with pytest.raises(InvalidStatusTransitionError):
        await env.accept_knowledge().handle(accept_knowledge_command(record_id))

    unchanged(env, record_id, status=status)


async def test_unknown_record_is_not_found() -> None:
    env = await make_review_env()

    with pytest.raises(RecordNotFoundError):
        await env.accept_knowledge().handle(
            accept_knowledge_command(RecordId(value="7" + "Z" * 25))
        )


async def test_preview_reports_the_result_and_writes_nothing() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    commits = env.store.commits

    result = await env.accept_knowledge().handle(
        accept_knowledge_command(record_id, None, apply=False)
    )

    assert (result.applied, result.status, result.pinned_revision) == (False, "accepted", 1)
    assert (result.decision_seq, result.basis) == (1, "agent_project")
    assert env.store.commits == commits
    unchanged(env, record_id, status=RecordStatusEnum.PROPOSED)


async def test_a_refused_preview_fails_like_the_applying_run() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1")

    with pytest.raises(ReviewNotAuthorisedError):
        await env.accept_knowledge().handle(accept_knowledge_command(record_id, None, apply=False))


async def test_replay_with_the_same_key_returns_the_first_result_without_a_second_decision() -> (
    None
):
    """AC-015."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    first = await env.accept_knowledge().handle(accept_knowledge_command(record_id, "same"))
    commits = env.store.commits

    again = await env.accept_knowledge().handle(accept_knowledge_command(record_id, "same"))

    assert again.replayed is True
    assert again == first.model_copy(update={"replayed": True})
    assert env.store.commits == commits
    assert env.store.knowledge[record_id.value].decision_seq == 1
    assert len(env.store.decisions[record_id.value]) == 1


async def test_same_key_with_another_reason_is_a_reused_key() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    await env.accept_knowledge().handle(accept_knowledge_command(record_id, "same"))

    with pytest.raises(IdempotencyKeyReusedError):
        await env.accept_knowledge().handle(
            accept_knowledge_command(record_id, "same", reason="other")
        )


async def test_losing_a_concurrent_decision_is_a_status_conflict() -> None:
    """AC-007 (unit): the competitor commits a reject between our read and our commit."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")

    async def competitor_rejects() -> None:
        async with env.uow() as uow:
            record = await uow.knowledge.get_for_update(record_id, space_id=env.space_id)
            assert record is not None
            record.reject(
                actor=USER, reason="race", basis=DecisionBasisEnum.USER, now=env.clock.now()
            )
            await uow.knowledge.save(record)
            await uow.commit()

    handler = env.accept_knowledge(racing_factory(env.store, competitor_rejects))

    with pytest.raises(StatusConflictError):
        await handler.handle(accept_knowledge_command(record_id, "a1"))

    stored = env.store.knowledge[record_id.value]
    assert stored.status is RecordStatusEnum.RETRACTED
    assert stored.decision_seq == 1
    assert len(env.store.decisions[record_id.value]) == 1
    assert (env.space_id.value, "a1") not in env.store.ledger


async def test_accept_needs_the_review_schema_step() -> None:
    env = await make_review_env(steps=("core",))
    record_id = await seed_knowledge(env, "c1", project="acme")

    with pytest.raises(StoreNotInitialisedError) as raised:
        await env.accept_knowledge().handle(accept_knowledge_command(record_id))

    assert raised.value.metadata["missing_steps"] == ["review"]
