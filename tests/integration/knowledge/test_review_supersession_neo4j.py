"""Supersession over the pinned Neo4j: AC-004, AC-006 (incl. repair) and the late-retraction edge cases."""

import pytest
from tests.support.knowledge_neo4j_support import query
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    repair_command,
    retract_assertion_command,
    retract_knowledge_command,
)
from tests.support.review_support import (
    CommitFailingFactory,
    ReviewNeo4jEnv,
    decisions_of,
    stored_status,
)

from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    SpaceId,
)
from noesis.exceptions import GraphStoreUnavailableError

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SUPERSEDES = AssertionPredicateEnum.SUPERSEDES


def _accept(assertion: RecordId, key: str) -> AcceptAssertionCommand:
    """Accept as the user: the records here are space-wide, which an agent may not decide."""
    return accept_assertion_command(assertion, key, actor=USER)


async def _pair(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId, RecordId]:
    """Accepted space-wide N and O, and a proposed `N supersedes O` (S)."""
    new = await env.seed_accepted("n", title="New rule")
    old = await env.seed_accepted("o", title="Old rule")
    return new, old, await env.propose(SUPERSEDES, new, old, "p-sup")


async def _state(env: ReviewNeo4jEnv, record_id: RecordId):
    states = await env.get_review_states.handle(
        GetReviewStatesQuery(space_key=Key(value="default"), record_ids=(record_id,))
    )
    return states[0]


async def _crash_between_the_two_units_of_work(
    env: ReviewNeo4jEnv, assertion: RecordId, key: str
) -> None:
    with pytest.raises(GraphStoreUnavailableError):
        await env.accept_assertion(CommitFailingFactory(env.uow, fail_on=2)).handle(
            _accept(assertion, key)
        )


async def _pending(env: ReviewNeo4jEnv) -> list[tuple[str, str]]:
    space_id = SpaceId(value=await env.space_id())
    pending = await env.base.persistence.review_state_read_repository.list_pending_effects(space_id)
    return [(p.assertion_id, p.object_id) for p in pending]


async def test_ac004_accepted_supersedes_marks_object(review_env: ReviewNeo4jEnv) -> None:
    new, old, supersedes = await _pair(review_env)

    accepted = await review_env.accept_assertion().handle(_accept(supersedes, "ac004"))

    assert [(e.record_id, e.outcome) for e in accepted.effects] == [(old.value, "applied")]
    state = await _state(review_env, old)
    assert (state.status, state.effective_status, state.authority) == (
        "superseded",
        "superseded",
        "superseded",
    )
    assert state.superseded_by_assertion_id == supersedes.value
    assert tuple(state.superseded_by_record_ids) == (new.value,)
    record = await review_env.base.get_record.handle(
        GetRecordQuery(space_key=Key(value="default"), record_id=old, revision=None)
    )
    assert record.revision is not None
    assert (record.revision.title, record.revision.body) == ("Old rule", "Use retries.")
    last = decisions_of(review_env.settings, old.value)[-1]
    assert (last["transition"], last["from_status"], last["to_status"]) == (
        "supersede",
        "accepted",
        "superseded",
    )
    assert last["cause_assertion_id"] == supersedes.value
    assert last["basis"] == "supersession_effect"
    assert (await _state(review_env, new)).status == "accepted"


async def test_ac006_interrupted_supersession_converges(review_env: ReviewNeo4jEnv) -> None:
    _, old, supersedes = await _pair(review_env)
    await _crash_between_the_two_units_of_work(review_env, supersedes, "ac006")

    state = await _state(review_env, old)
    assert (state.status, state.effective_status, state.authority) == (
        "accepted",
        "superseded",
        "superseded",
    )
    assert await _pending(review_env) == [(supersedes.value, old.value)]

    replayed = await review_env.accept_assertion().handle(_accept(supersedes, "ac006"))

    assert [(e.record_id, e.outcome) for e in replayed.effects] == [(old.value, "applied")]
    assert stored_status(review_env.settings, old.value) == "superseded"
    assert [d["seq"] for d in decisions_of(review_env.settings, supersedes.value)] == [1]
    assert await _pending(review_env) == []


async def test_ac006_repair_applies_pending_effect(review_env: ReviewNeo4jEnv) -> None:
    _, old, supersedes = await _pair(review_env)
    await _crash_between_the_two_units_of_work(review_env, supersedes, "ac006-repair")

    repaired = await review_env.repair().handle(repair_command())
    again = await review_env.repair().handle(repair_command())

    assert [(e.assertion_id, e.record_id, e.outcome) for e in repaired.effects] == [
        (supersedes.value, old.value, "applied")
    ]
    assert again.effects == ()
    assert stored_status(review_env.settings, old.value) == "superseded"
    assert [d["transition"] for d in decisions_of(review_env.settings, old.value)] == [
        "accept",
        "supersede",
    ]


async def test_repair_preview_reports_the_effect_and_writes_nothing(
    review_env: ReviewNeo4jEnv,
) -> None:
    _, old, supersedes = await _pair(review_env)
    await _crash_between_the_two_units_of_work(review_env, supersedes, "ac006-preview")

    preview = await review_env.repair().handle(repair_command(apply=False))

    assert preview.applied is False
    assert [(e.assertion_id, e.record_id) for e in preview.effects] == [
        (supersedes.value, old.value)
    ]
    assert stored_status(review_env.settings, old.value) == "accepted"


async def test_retracting_s_later_does_not_reinstate_o_or_touch_other_assertions(
    review_env: ReviewNeo4jEnv,
) -> None:
    _, old, supersedes = await _pair(review_env)
    evidence = await review_env.capture_experience()
    about_old = await review_env.propose(AssertionPredicateEnum.SUPPORTS, evidence, old, "about-o")
    await review_env.accept_assertion().handle(_accept(supersedes, "ac004"))
    decisions_before = decisions_of(review_env.settings, old.value)

    retracted = await review_env.retract_assertion().handle(
        retract_assertion_command(supersedes, "ret-s", reason="changed my mind")
    )

    assert retracted.outcome == "retracted"
    assert stored_status(review_env.settings, supersedes.value) == "retracted"
    state = await _state(review_env, old)
    assert (state.status, state.effective_status) == ("superseded", "superseded")
    assert decisions_of(review_env.settings, old.value) == decisions_before
    assert stored_status(review_env.settings, about_old.value) == "proposed"


async def test_object_retracted_before_the_effect_is_skipped_on_replay(
    review_env: ReviewNeo4jEnv,
) -> None:
    _, old, supersedes = await _pair(review_env)
    await _crash_between_the_two_units_of_work(review_env, supersedes, "o-retracted")
    await review_env.retract_knowledge().handle(
        retract_knowledge_command(old, "ret-o", reason="wrong anyway")
    )

    replayed = await review_env.accept_assertion().handle(_accept(supersedes, "o-retracted"))

    assert [(e.record_id, e.outcome, e.reason) for e in replayed.effects] == [
        (old.value, "skipped", "object_not_accepted")
    ]
    state = await _state(review_env, old)
    assert (state.status, state.effective_status) == ("retracted", "superseded")
    assert await _pending(review_env) == []
    assert [d["transition"] for d in decisions_of(review_env.settings, old.value)] == [
        "accept",
        "retract",
    ]
    assert query(
        review_env.settings,
        "MATCH (k:Knowledge {id: $id}) RETURN k.superseded_by_assertion_id AS s",
        id=old.value,
    ) == [{"s": None}]
