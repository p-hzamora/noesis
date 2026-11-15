"""RetractKnowledgeHandler: reject a proposal, retract accepted knowledge (FR-004..FR-006, FR-015;
AC-007, AC-015; edge cases)."""

import pytest
from pydantic import ValidationError
from tests.support.knowledge_commands import racing_factory
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import (
    USER,
    accept_knowledge_command,
    retract_knowledge_command,
)
from tests.support.review_fakes import ReviewEnv, make_review_env, seed_knowledge

from noesis.bounded_context.knowledge.application.dtos.review_dtos import RetractResultDto
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    InvalidStatusTransitionError,
    RecordNotFoundError,
    ReviewNotAuthorisedError,
    StatusConflictError,
)

pytestmark = pytest.mark.unit

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED


def stored_status(env: ReviewEnv, record_id: RecordId) -> RecordStatusEnum:
    return env.store.knowledge[record_id.value].status


async def test_retracting_a_proposal_is_a_rejection() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")

    result = await env.retract_knowledge().handle(
        retract_knowledge_command(record_id, "r1", reason="wrong")
    )

    assert isinstance(result, RetractResultDto)
    assert (result.id, result.status, result.outcome) == (record_id.value, "retracted", "rejected")
    assert (result.applied, result.replayed) == (True, False)
    stored = env.store.knowledge[record_id.value]
    assert stored.status is RETRACTED
    decision = stored.latest_decision
    assert decision is not None
    assert (decision.transition, decision.from_status, decision.to_status) == (
        ReviewTransitionEnum.REJECT,
        PROPOSED,
        RETRACTED,
    )
    assert (decision.reason, decision.basis, decision.actor) == (
        "wrong",
        DecisionBasisEnum.USER,
        USER,
    )
    assert decision.pinned_revision is None
    ledger = env.store.ledger[(env.space_id.value, "r1")]
    assert (ledger.command, ledger.record_id) == ("review.retract", record_id)


async def test_retracting_accepted_knowledge_is_a_retraction() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme", status=ACCEPTED)

    result = await env.retract_knowledge().handle(retract_knowledge_command(record_id))

    decision = env.store.knowledge[record_id.value].latest_decision
    assert (result.outcome, result.status) == ("retracted", "retracted")
    assert decision is not None
    assert (decision.transition, decision.from_status) == (ReviewTransitionEnum.RETRACT, ACCEPTED)


async def test_agent_may_reject_project_knowledge_with_basis_agent_project() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")

    await env.retract_knowledge().handle(retract_knowledge_command(record_id, actor=AGENT))

    decision = env.store.knowledge[record_id.value].latest_decision
    assert decision is not None
    assert (decision.basis, decision.actor) == (DecisionBasisEnum.AGENT_PROJECT, AGENT)


@pytest.mark.parametrize("status", [PROPOSED, ACCEPTED])
async def test_agent_cannot_reject_or_retract_global_knowledge(status: RecordStatusEnum) -> None:
    """Q-004 default."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", status=status)

    with pytest.raises(ReviewNotAuthorisedError):
        await env.retract_knowledge().handle(retract_knowledge_command(record_id, actor=AGENT))

    assert stored_status(env, record_id) is status
    assert env.store.knowledge[record_id.value].latest_decision is None


@pytest.mark.parametrize("status", [SUPERSEDED, RETRACTED])
async def test_knowledge_that_is_superseded_or_retracted_cannot_be_retracted(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme", status=status)

    with pytest.raises(InvalidStatusTransitionError):
        await env.retract_knowledge().handle(retract_knowledge_command(record_id))

    assert stored_status(env, record_id) is status


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_retract_command_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValidationError):
        retract_knowledge_command(RecordId(value="0" * 25 + "1"), reason=reason)


async def test_unknown_record_is_not_found() -> None:
    env = await make_review_env()

    with pytest.raises(RecordNotFoundError):
        await env.retract_knowledge().handle(
            retract_knowledge_command(RecordId(value="7" + "Z" * 25))
        )


async def test_preview_reports_the_outcome_and_writes_nothing() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    commits = env.store.commits

    result = await env.retract_knowledge().handle(
        retract_knowledge_command(record_id, None, apply=False)
    )

    assert (result.applied, result.outcome, result.status) == (False, "rejected", "retracted")
    assert env.store.commits == commits
    assert stored_status(env, record_id) is PROPOSED


async def test_replay_returns_the_first_result_and_a_different_reason_is_a_reused_key() -> None:
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")
    first = await env.retract_knowledge().handle(retract_knowledge_command(record_id, "same"))
    commits = env.store.commits

    again = await env.retract_knowledge().handle(retract_knowledge_command(record_id, "same"))

    assert again == first.model_copy(update={"replayed": True})
    assert env.store.commits == commits
    assert len(env.store.decisions[record_id.value]) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await env.retract_knowledge().handle(
            retract_knowledge_command(record_id, "same", reason="other")
        )


async def test_losing_the_race_to_an_accept_is_a_status_conflict() -> None:
    """AC-007 (unit): the accept commits first, so only one decision exists."""
    env = await make_review_env()
    record_id = await seed_knowledge(env, "c1", project="acme")

    async def competitor_accepts() -> None:
        await env.accept_knowledge().handle(accept_knowledge_command(record_id, "win"))

    handler = env.retract_knowledge(racing_factory(env.store, competitor_accepts))

    with pytest.raises(StatusConflictError):
        await handler.handle(retract_knowledge_command(record_id, "lose", actor=AGENT))

    assert stored_status(env, record_id) is ACCEPTED
    assert len(env.store.decisions[record_id.value]) == 1
