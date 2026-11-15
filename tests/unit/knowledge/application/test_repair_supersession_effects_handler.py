"""RepairSupersessionEffectsHandler: `review repair` (FR-009, FR-015; AC-006)."""

import pytest
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    repair_command,
    retract_knowledge_command,
)
from tests.support.review_fakes import (
    RecordingUowFactory,
    ReviewEnv,
    make_review_env,
    seed_assertion,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import GraphStoreUnavailableError

pytestmark = pytest.mark.unit

ACCEPTED = RecordStatusEnum.ACCEPTED


async def pending_supersession(env: ReviewEnv, key: str) -> tuple[RecordId, RecordId]:
    n = await seed_knowledge(env, f"n-{key}", status=ACCEPTED)
    o = await seed_knowledge(env, f"o-{key}", status=ACCEPTED)
    s = await seed_assertion(env, AssertionPredicateEnum.SUPERSEDES, n, o, status=ACCEPTED)
    return s, o


async def test_repair_applies_the_pending_effect_and_a_second_run_finds_nothing() -> None:
    env = await make_review_env()
    s, o = await pending_supersession(env, "1")

    first = await env.repair().handle(repair_command())
    second = await env.repair().handle(repair_command())

    assert first.applied is True
    assert [(e.assertion_id, e.record_id, e.outcome) for e in first.effects] == [
        (s.value, o.value, "applied")
    ]
    assert env.store.knowledge[o.value].status is RecordStatusEnum.SUPERSEDED
    assert env.store.knowledge[o.value].superseded_by_assertion_id == s
    assert second.effects == ()
    assert len(env.store.decisions[o.value]) == 1


async def test_repair_after_an_injected_crash_converges() -> None:
    """AC-006 repair path."""
    env = await make_review_env()
    evidence = await seed_experience(env)
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    o = await seed_knowledge(env, "o", status=ACCEPTED)
    s = await seed_assertion(env, AssertionPredicateEnum.SUPERSEDES, n, o, evidence=(evidence,))
    with pytest.raises(GraphStoreUnavailableError):
        await env.accept_assertion(RecordingUowFactory(env.store, fail_on_commit=2)).handle(
            accept_assertion_command(s, "k1", actor=USER)
        )

    result = await env.repair().handle(repair_command())

    assert [(e.assertion_id, e.record_id, e.outcome) for e in result.effects] == [
        (s.value, o.value, "applied")
    ]
    assert env.store.knowledge[o.value].status is RecordStatusEnum.SUPERSEDED
    assert (await env.repair().handle(repair_command())).effects == ()


async def test_preview_lists_what_would_be_applied_and_writes_nothing() -> None:
    env = await make_review_env()
    s, o = await pending_supersession(env, "1")
    commits = env.store.commits

    result = await env.repair().handle(repair_command(apply=False))

    assert result.applied is False
    assert [(e.assertion_id, e.record_id, e.outcome) for e in result.effects] == [
        (s.value, o.value, "applied")
    ]
    assert env.store.commits == commits
    assert env.store.knowledge[o.value].status is ACCEPTED


async def test_an_effect_whose_object_was_retracted_is_no_longer_pending() -> None:
    env = await make_review_env()
    _, o = await pending_supersession(env, "1")
    await env.retract_knowledge().handle(retract_knowledge_command(o))

    result = await env.repair().handle(repair_command())

    assert result.effects == ()
    assert env.store.knowledge[o.value].status is RecordStatusEnum.RETRACTED


async def test_repair_handles_every_pending_effect() -> None:
    env = await make_review_env()
    first = await pending_supersession(env, "1")
    second = await pending_supersession(env, "2")

    result = await env.repair().handle(repair_command())

    assert {e.record_id for e in result.effects} == {first[1].value, second[1].value}
    assert all(e.outcome == "applied" for e in result.effects)
