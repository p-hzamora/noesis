"""ListAssertionsBySubjectsHandler: the batch read the retrieval adapter maps (FR-017; AC-021)."""

import pytest
from tests.support.review_fakes import (
    ReviewEnv,
    make_review_env,
    seed_assertion,
    seed_catalog_entry,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import AssertionSummaryDto
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_by_subjects_handler import (
    ListAssertionsBySubjectsQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import SpaceNotFoundError, StoreNotInitialisedError

pytestmark = pytest.mark.unit

RECOMMENDS = AssertionPredicateEnum.RECOMMENDS
SUPPORTS = AssertionPredicateEnum.SUPPORTS
PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED


def query(
    *subjects: RecordId,
    predicates: tuple[AssertionPredicateEnum, ...] = (),
    statuses: tuple[RecordStatusEnum, ...] = (),
    space: str = "default",
) -> ListAssertionsBySubjectsQuery:
    return ListAssertionsBySubjectsQuery(
        space_key=Key(value=space),
        subject_ids=subjects,
        predicates=predicates,
        statuses=statuses,
    )


async def fixture(env: ReviewEnv) -> dict[str, RecordId]:
    """K1, K2, K3 and catalog C1 in acme; A1..A4 as in AC-021."""
    k1 = await seed_knowledge(env, "k1", project="acme", status=ACCEPTED)
    k2 = await seed_knowledge(env, "k2", project="acme", status=ACCEPTED)
    k3 = await seed_knowledge(env, "k3", project="acme", status=ACCEPTED)
    c1 = seed_catalog_entry(env)
    evidence = await seed_experience(env)
    a1 = await seed_assertion(
        env, RECOMMENDS, k1, c1, project="acme", evidence=(evidence,), status=ACCEPTED
    )
    a2 = await seed_assertion(env, SUPPORTS, k1, k2, project="acme")
    a3 = await seed_assertion(env, RECOMMENDS, k2, k3, project="acme")
    a4 = await seed_assertion(
        env, RECOMMENDS, k3, c1, project="acme", status=RecordStatusEnum.RETRACTED
    )
    return {
        "k1": k1,
        "k2": k2,
        "k3": k3,
        "c1": c1,
        "a1": a1,
        "a2": a2,
        "a3": a3,
        "a4": a4,
        "evidence": evidence,
    }


async def test_filters_by_subject_predicate_and_status_and_describes_the_object() -> None:
    env = await make_review_env()
    r = await fixture(env)

    summaries = await env.list_assertions_by_subjects.handle(
        query(r["k1"], r["k2"], predicates=(RECOMMENDS,), statuses=(ACCEPTED, PROPOSED))
    )

    assert all(isinstance(s, AssertionSummaryDto) for s in summaries)
    assert [s.assertion_id for s in summaries] == [r["a1"].value, r["a3"].value]
    a1, a3 = summaries
    assert (a1.object_type, a1.object_id, a1.object_at_revision) == (
        "catalog_entry",
        r["c1"].value,
        None,
    )
    assert (a3.object_type, a3.object_id, a3.object_at_revision) == (
        "knowledge",
        r["k3"].value,
        1,
    )
    assert (a1.subject_id, a1.subject_at_revision) == (r["k1"].value, 1)
    assert (a1.predicate, a1.status, a1.project_key) == ("recommends", "accepted", "acme")
    assert a1.evidence_ids == (r["evidence"].value,)
    assert a3.evidence_ids == ()


async def test_a_retracted_assertion_is_found_when_that_status_is_asked_for() -> None:
    env = await make_review_env()
    r = await fixture(env)

    summaries = await env.list_assertions_by_subjects.handle(
        query(r["k3"], statuses=(RecordStatusEnum.RETRACTED,))
    )

    assert [s.assertion_id for s in summaries] == [r["a4"].value]


async def test_no_filters_means_every_assertion_of_the_subjects() -> None:
    env = await make_review_env()
    r = await fixture(env)

    summaries = await env.list_assertions_by_subjects.handle(query(r["k1"]))

    assert [s.assertion_id for s in summaries] == [r["a1"].value, r["a2"].value]


async def test_no_subject_ids_gives_an_empty_list() -> None:
    env = await make_review_env()
    await fixture(env)

    assert await env.list_assertions_by_subjects.handle(query()) == []


async def test_an_unknown_space_is_reported() -> None:
    env = await make_review_env()

    with pytest.raises(SpaceNotFoundError):
        await env.list_assertions_by_subjects.handle(
            query(RecordId(value="7" + "Z" * 25), space="no")
        )


async def test_the_review_schema_step_is_required() -> None:
    env = await make_review_env(steps=("core",))

    with pytest.raises(StoreNotInitialisedError):
        await env.list_assertions_by_subjects.handle(query(RecordId(value="7" + "Z" * 25)))
