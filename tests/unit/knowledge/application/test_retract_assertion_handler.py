"""RetractAssertionHandler: reject or retract an assertion (FR-004..FR-006, FR-015; AC-010)."""

import pytest
from pydantic import ValidationError
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import USER, retract_assertion_command
from tests.support.review_fakes import (
    ReviewEnv,
    make_review_env,
    seed_assertion,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    InvalidStatusTransitionError,
    RecordNotFoundError,
    ReviewNotAuthorisedError,
)

pytestmark = pytest.mark.unit

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED


async def assertion_in(
    env: ReviewEnv, *, project: str | None = None, status: RecordStatusEnum = PROPOSED
) -> RecordId:
    subject = await seed_knowledge(env, "c1", project=project, status=ACCEPTED)
    object_ = await seed_knowledge(env, "c2", project=project, status=ACCEPTED)
    return await seed_assertion(
        env, AssertionPredicateEnum.SUPPORTS, subject, object_, project=project, status=status
    )


@pytest.mark.parametrize(
    ("status", "outcome", "transition"),
    [
        (PROPOSED, "rejected", ReviewTransitionEnum.REJECT),
        (ACCEPTED, "retracted", ReviewTransitionEnum.RETRACT),
    ],
)
async def test_proposal_is_rejected_and_accepted_assertion_is_retracted(
    status: RecordStatusEnum, outcome: str, transition: ReviewTransitionEnum
) -> None:
    env = await make_review_env()
    assertion = await assertion_in(env, status=status)

    result = await env.retract_assertion().handle(
        retract_assertion_command(assertion, "r1", reason="dup")
    )

    stored = env.store.assertions[assertion.value]
    decision = stored.latest_decision
    assert (result.status, result.outcome, result.applied) == ("retracted", outcome, True)
    assert stored.status is RETRACTED
    assert decision is not None
    assert (decision.transition, decision.from_status, decision.reason) == (
        transition,
        status,
        "dup",
    )
    assert decision.basis is DecisionBasisEnum.USER
    ledger = env.store.ledger[(env.space_id.value, "r1")]
    assert (ledger.command, ledger.record_id) == ("review.retract", assertion)


async def test_agent_may_retract_a_project_assertion_without_evidence() -> None:
    env = await make_review_env()
    assertion = await assertion_in(env, project="acme")

    result = await env.retract_assertion().handle(retract_assertion_command(assertion, actor=AGENT))

    assert result.outcome == "rejected"
    decision = env.store.assertions[assertion.value].latest_decision
    assert decision is not None
    assert decision.basis is DecisionBasisEnum.AGENT_PROJECT


@pytest.mark.parametrize("status", [PROPOSED, ACCEPTED])
async def test_agent_cannot_reject_or_retract_a_global_assertion(status: RecordStatusEnum) -> None:
    env = await make_review_env()
    assertion = await assertion_in(env, status=status)

    with pytest.raises(ReviewNotAuthorisedError):
        await env.retract_assertion().handle(retract_assertion_command(assertion, actor=AGENT))

    assert env.store.assertions[assertion.value].status is status


@pytest.mark.parametrize("status", [SUPERSEDED, RETRACTED])
async def test_an_assertion_that_is_superseded_or_retracted_cannot_be_retracted(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    assertion = await assertion_in(env, status=status)

    with pytest.raises(InvalidStatusTransitionError):
        await env.retract_assertion().handle(retract_assertion_command(assertion, actor=USER))

    assert env.store.assertions[assertion.value].status is status


def test_a_retract_command_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        retract_assertion_command(RecordId(value="0" * 25 + "1"), reason="")


async def test_unknown_assertion_is_not_found() -> None:
    env = await make_review_env()

    with pytest.raises(RecordNotFoundError):
        await env.retract_assertion().handle(
            retract_assertion_command(RecordId(value="7" + "Z" * 25))
        )


async def test_preview_writes_nothing() -> None:
    env = await make_review_env()
    assertion = await assertion_in(env)
    commits = env.store.commits

    result = await env.retract_assertion().handle(
        retract_assertion_command(assertion, None, apply=False)
    )

    assert (result.applied, result.outcome) == (False, "rejected")
    assert env.store.commits == commits
    assert env.store.assertions[assertion.value].status is PROPOSED


async def test_replay_by_key_writes_nothing_and_a_different_request_is_a_reused_key() -> None:
    env = await make_review_env()
    assertion = await assertion_in(env)
    first = await env.retract_assertion().handle(retract_assertion_command(assertion, "same"))
    commits = env.store.commits

    again = await env.retract_assertion().handle(retract_assertion_command(assertion, "same"))

    assert again == first.model_copy(update={"replayed": True})
    assert env.store.commits == commits
    with pytest.raises(IdempotencyKeyReusedError):
        await env.retract_assertion().handle(
            retract_assertion_command(assertion, "same", reason="another")
        )
