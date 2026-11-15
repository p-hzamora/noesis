"""GetReviewStatesHandler: stored, effective status and authority per record (FR-017; AC-020)."""

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.review_commands import USER, accept_knowledge_command
from tests.support.review_fakes import (
    ReviewEnv,
    force_status,
    make_review_env,
    seed_assertion,
    seed_catalog_entry,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import ReviewStateDto
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import SpaceNotFoundError, StoreNotInitialisedError

pytestmark = pytest.mark.unit

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED


def query(*ids: RecordId, space: str = "default") -> GetReviewStatesQuery:
    return GetReviewStatesQuery(space_key=Key(value=space), record_ids=ids)


async def test_one_state_per_id_with_the_derived_status_and_authority() -> None:
    """AC-020 (unit): the derivation table end to end, one call for every record."""
    env = await make_review_env()
    proposed = await seed_knowledge(env, "k-proposed")
    accepted = await seed_knowledge(env, "k-accepted", status=ACCEPTED)
    revised_then_accepted = await seed_knowledge(env, "k-revised")
    await env.base.revise_knowledge.handle(revise_command(revised_then_accepted))
    force_status(env, revised_then_accepted, ACCEPTED)
    effect_pending = await seed_knowledge(env, "k-pending", status=ACCEPTED)
    stored_superseded = await seed_knowledge(env, "k-superseded", status=SUPERSEDED)
    retracted = await seed_knowledge(env, "k-retracted", status=RETRACTED)
    experience = await seed_experience(env)
    catalog_entry = seed_catalog_entry(env)
    successor = await seed_knowledge(env, "k-successor", status=ACCEPTED)
    await seed_assertion(
        env, AssertionPredicateEnum.SUPERSEDES, successor, effect_pending, status=ACCEPTED
    )
    accepted_assertion = await seed_assertion(
        env, AssertionPredicateEnum.SUPPORTS, experience, accepted, status=ACCEPTED
    )
    ids = (
        proposed,
        accepted,
        revised_then_accepted,
        effect_pending,
        stored_superseded,
        retracted,
        experience,
        catalog_entry,
        accepted_assertion,
    )

    states = await env.get_review_states.handle(query(*ids))

    assert all(isinstance(s, ReviewStateDto) for s in states)
    assert [
        (s.record_id, s.record_type, s.status, s.effective_status, s.authority, s.head_revision)
        for s in states
    ] == [
        (proposed.value, "knowledge", "proposed", "proposed", "proposed", 1),
        (accepted.value, "knowledge", "accepted", "accepted", "authoritative", 1),
        (revised_then_accepted.value, "knowledge", "accepted", "accepted", "authoritative", 2),
        (effect_pending.value, "knowledge", "accepted", "superseded", "superseded", 1),
        (stored_superseded.value, "knowledge", "superseded", "superseded", "superseded", 1),
        (retracted.value, "knowledge", "retracted", "retracted", "retracted", 1),
        (experience.value, "experience", None, None, "not_reviewable", None),
        (catalog_entry.value, "catalog_entry", None, None, "not_reviewable", None),
        (accepted_assertion.value, "assertion", "accepted", "accepted", "authoritative", None),
    ]


async def test_a_record_targeted_by_an_accepted_supersedes_names_it_and_its_subject() -> None:
    env = await make_review_env()
    successor = await seed_knowledge(env, "n", status=ACCEPTED)
    original = await seed_knowledge(env, "o", status=ACCEPTED)
    plain = await seed_knowledge(env, "p", status=ACCEPTED)
    s = await seed_assertion(
        env, AssertionPredicateEnum.SUPERSEDES, successor, original, status=ACCEPTED
    )

    by_id = {st.record_id: st for st in await env.get_review_states.handle(query(original, plain))}

    assert by_id[original.value].superseded_by_assertion_id == s.value
    assert by_id[original.value].superseded_by_record_ids == (successor.value,)
    assert by_id[plain.value].superseded_by_assertion_id is None
    assert by_id[plain.value].superseded_by_record_ids == ()


async def test_scope_tags_and_the_latest_decision_are_reported() -> None:
    env = await make_review_env()
    scoped = await seed_knowledge(env, "c1", project="acme", tags=("lang:python", "area:retry"))
    undecided = await seed_knowledge(env, "c2")
    await env.accept_knowledge().handle(accept_knowledge_command(scoped, actor=USER))

    by_id = {s.record_id: s for s in await env.get_review_states.handle(query(scoped, undecided))}

    assert by_id[scoped.value].project_key == "acme"
    assert by_id[scoped.value].tags == ("area:retry", "lang:python")
    assert by_id[scoped.value].decided_by_kind == "user"
    assert by_id[scoped.value].decided_at == env.clock.now().isoformat()
    assert by_id[undecided.value].project_key is None
    assert by_id[undecided.value].tags == ()
    assert (by_id[undecided.value].decided_by_kind, by_id[undecided.value].decided_at) == (
        None,
        None,
    )


async def test_ids_unknown_in_the_space_are_not_returned() -> None:
    env = await make_review_env()
    known = await seed_knowledge(env, "c1")

    states = await env.get_review_states.handle(query(RecordId(value="7" + "Z" * 25), known))

    assert [s.record_id for s in states] == [known.value]


async def test_an_unknown_space_is_reported() -> None:
    env = await make_review_env()

    with pytest.raises(SpaceNotFoundError):
        await env.get_review_states.handle(query(RecordId(value="7" + "Z" * 25), space="nowhere"))


async def test_the_review_schema_step_is_required() -> None:
    env: ReviewEnv = await make_review_env(steps=("core",))

    with pytest.raises(StoreNotInitialisedError) as raised:
        await env.get_review_states.handle(query(RecordId(value="7" + "Z" * 25)))

    assert raised.value.metadata["missing_steps"] == ["review"]
