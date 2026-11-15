"""ApplySupersessionHandler: the convergent effect step (FR-009, FR-015; AC-004, AC-006)."""

import pytest
from tests.support.review_commands import USER, apply_supersession_command
from tests.support.review_fakes import (
    RecordingUowFactory,
    ReviewEnv,
    force_status,
    make_review_env,
    seed_assertion,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import EffectDto
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import StatusConflictError

pytestmark = pytest.mark.unit

ACCEPTED, SUPERSEDED = RecordStatusEnum.ACCEPTED, RecordStatusEnum.SUPERSEDED


async def accepted_pair(env: ReviewEnv) -> tuple[RecordId, RecordId, RecordId]:
    """N, O accepted and S 'N supersedes O' accepted, with the effect not yet applied."""
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    o = await seed_knowledge(env, "o", status=ACCEPTED)
    s = await seed_assertion(env, AssertionPredicateEnum.SUPERSEDES, n, o, status=ACCEPTED)
    return n, o, s


async def test_applies_the_effect_to_an_accepted_object() -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)

    effect = await env.apply_supersession().handle(apply_supersession_command(s, o))

    assert isinstance(effect, EffectDto)
    assert (effect.record_id, effect.outcome, effect.reason) == (o.value, "applied", None)
    assert effect.assertion_id == s.value
    stored = env.store.knowledge[o.value]
    assert stored.status is SUPERSEDED
    assert stored.superseded_by_assertion_id == s
    decision = stored.latest_decision
    assert decision is not None
    assert (decision.transition, decision.basis, decision.cause_assertion_id) == (
        ReviewTransitionEnum.SUPERSEDE,
        DecisionBasisEnum.SUPERSESSION_EFFECT,
        s,
    )


async def test_the_decision_names_the_actor_of_the_command_running_the_effect() -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)

    await env.apply_supersession().handle(apply_supersession_command(s, o, actor=USER))

    decision = env.store.knowledge[o.value].latest_decision
    assert decision is not None
    assert decision.actor == USER


async def test_a_second_run_reports_applied_and_writes_nothing() -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)
    await env.apply_supersession().handle(apply_supersession_command(s, o))
    commits = env.store.commits

    again = await env.apply_supersession().handle(apply_supersession_command(s, o))

    assert again.outcome == "applied"
    assert env.store.commits == commits
    assert env.store.knowledge[o.value].decision_seq == 1
    assert len(env.store.decisions[o.value]) == 1


@pytest.mark.parametrize("status", [RecordStatusEnum.RETRACTED, RecordStatusEnum.PROPOSED])
async def test_an_object_that_is_not_accepted_is_skipped_and_untouched(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)
    force_status(env, o, status)
    commits = env.store.commits

    effect = await env.apply_supersession().handle(apply_supersession_command(s, o))

    assert (effect.outcome, effect.reason) == ("skipped", "object_not_accepted")
    assert env.store.commits == commits
    assert env.store.knowledge[o.value].status is status
    assert env.store.knowledge[o.value].latest_decision is None


async def test_an_object_already_superseded_by_another_assertion_is_skipped() -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)
    other_successor = await seed_knowledge(env, "n2", status=ACCEPTED)
    other = await seed_assertion(
        env, AssertionPredicateEnum.SUPERSEDES, other_successor, o, status=ACCEPTED
    )
    await env.apply_supersession().handle(apply_supersession_command(other, o))

    effect = await env.apply_supersession().handle(apply_supersession_command(s, o))

    assert (effect.outcome, effect.reason) == ("skipped", "object_not_accepted")
    assert env.store.knowledge[o.value].superseded_by_assertion_id == other


async def test_losing_the_object_decision_key_race_is_skipped_as_concurrent() -> None:
    env = await make_review_env()
    _, o, s = await accepted_pair(env)
    lost = RecordingUowFactory(
        env.store, fail_on_commit=1, error=StatusConflictError("lost", {"record_id": o.value})
    )

    effect = await env.apply_supersession(lost).handle(apply_supersession_command(s, o))

    assert (effect.outcome, effect.reason) == ("skipped", "concurrent_decision")
    assert env.store.knowledge[o.value].status is ACCEPTED
