"""The review read models over the pinned Neo4j: queue (AC-014, AC-024), states (AC-020), by subjects (AC-021)."""

from typing import Any

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.knowledge_neo4j_support import query
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    accept_knowledge_command,
    retract_assertion_command,
    retract_knowledge_command,
)
from tests.support.review_support import CommitFailingFactory, ReviewNeo4jEnv

from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_by_subjects_handler import (
    ListAssertionsBySubjectsQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
)
from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    RecordReviewStateContract,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SPACE_KEY = Key(value="default")
SUPPORTS = AssertionPredicateEnum.SUPPORTS
RECOMMENDS = AssertionPredicateEnum.RECOMMENDS
SUPERSEDES = AssertionPredicateEnum.SUPERSEDES


def _queue(actor: Actor, **overrides: Any) -> ListReviewQueueQuery:
    return ListReviewQueueQuery(space_key=SPACE_KEY, actor=actor, **overrides)


# --- AC-014 -------------------------------------------------------------------------------------


async def _queue_fixture(env: ReviewNeo4jEnv) -> dict[str, RecordId]:
    experience = await env.capture_experience()
    k_p = await env.capture("kp", project="acme")
    k_q = await env.capture("kq", project="other")
    k_g = await env.capture("kg")
    k_a = await env.seed_accepted("ka", project="acme")
    a_p = await env.propose(SUPPORTS, experience, k_p, "ap", evidence=(experience,), project="acme")
    return {"e": experience, "k_p": k_p, "k_q": k_q, "k_g": k_g, "k_a": k_a, "a_p": a_p}


async def test_ac014_queue_scope_and_decidability(review_env: ReviewNeo4jEnv) -> None:
    ids = await _queue_fixture(review_env)
    proposed = {ids["k_p"].value, ids["a_p"].value, ids["k_q"].value, ids["k_g"].value}

    for_project = await review_env.list_review_queue.handle(
        _queue(AGENT, project=Key(value="acme"))
    )
    only_global = await review_env.list_review_queue.handle(_queue(AGENT, global_only=True))
    everything = await review_env.list_review_queue.handle(_queue(AGENT))
    as_user = await review_env.list_review_queue.handle(_queue(USER))
    assertions = await review_env.list_review_queue.handle(
        _queue(AGENT, record_type=RecordTypeEnum.ASSERTION)
    )

    listed = [item.id for item in for_project.items]
    assert set(listed) == {ids["k_p"].value, ids["a_p"].value, ids["k_g"].value}
    assert listed == sorted(listed)
    by_id = {item.id: item for item in for_project.items}
    for decidable in (ids["k_p"], ids["a_p"]):
        assert by_id[decidable.value].requires == "agent_or_user"
        assert by_id[decidable.value].decidable_by_caller is True
    assert by_id[ids["k_g"].value].requires == "user"
    assert by_id[ids["k_g"].value].decidable_by_caller is False
    assert by_id[ids["a_p"].value].evidence_count == 1
    assert by_id[ids["k_p"].value].evidence_count is None
    assert by_id[ids["k_p"].value].type == "knowledge"
    assert by_id[ids["a_p"].value].type == "assertion"
    assert by_id[ids["k_p"].value].title == "Retry policy"
    assert all(not hasattr(item, "drifted") for item in for_project.items)
    assert [item.id for item in only_global.items] == [ids["k_g"].value]
    assert {item.id for item in everything.items} == proposed
    assert all(item.decidable_by_caller is True for item in as_user.items)
    assert {item.id for item in as_user.items} == proposed
    assert [item.id for item in assertions.items] == [ids["a_p"].value]


async def test_ac014_queue_pagination(review_env: ReviewNeo4jEnv) -> None:
    await _queue_fixture(review_env)

    first = await review_env.list_review_queue.handle(_queue(AGENT, limit=2))
    assert len(first.items) == 2 and first.next_cursor
    second = await review_env.list_review_queue.handle(
        _queue(AGENT, limit=2, cursor=first.next_cursor)
    )

    walked = [item.id for item in (*first.items, *second.items)]
    assert len(walked) == 4 and len(set(walked)) == 4
    assert walked == sorted(walked)
    assert second.next_cursor is None


# --- AC-024 -------------------------------------------------------------------------------------


async def test_ac024_queue_consolidation_id(review_env: ReviewNeo4jEnv) -> None:
    old = await review_env.seed_accepted("old")
    new = await review_env.capture("new")
    other = await review_env.capture("other")
    successor = await review_env.propose(SUPERSEDES, new, old, "sup")
    query(
        review_env.settings,
        "CREATE (c:Consolidation {id: 'c-1', space_id: 'default'}) WITH c "
        "MATCH (r:Record) WHERE r.id IN [$new, $successor] CREATE (c)-[:PRODUCED]->(r)",
        new=new.value,
        successor=successor.value,
    )

    page = await review_env.list_review_queue.handle(_queue(USER))

    by_id = {item.id: item.consolidation_id for item in page.items}
    assert by_id == {new.value: "c-1", successor.value: "c-1", other.value: None}


async def test_ac024_queue_without_any_consolidation_node_has_null_links_and_no_warning(
    review_env: ReviewNeo4jEnv,
) -> None:
    """`filterwarnings = error`: an optional match over the absent label must stay silent."""
    record = await review_env.capture("k", project="acme")
    assert query(review_env.settings, "MATCH (c:Consolidation) RETURN count(c) AS total") == [
        {"total": 0}
    ]

    page = await review_env.list_review_queue.handle(_queue(USER))

    assert [(item.id, item.consolidation_id) for item in page.items] == [(record.value, None)]


# --- AC-020 -------------------------------------------------------------------------------------


async def test_ac020_review_state_contract(review_env: ReviewNeo4jEnv) -> None:
    env = review_env
    proposed = await env.capture("p", project="acme")
    authoritative = await env.seed_accepted("a", project="acme")
    revised = await env.capture("r2", project="acme")
    await env.base.revise_knowledge.handle(revise_command(revised, "rv", expected=1))
    await env.accept_knowledge().handle(
        accept_knowledge_command(revised, "r2-acc", expected=2, actor=USER)
    )
    pending_new = await env.seed_accepted("pn")
    pending_old = await env.seed_accepted("po")
    pending_effect = await env.propose(SUPERSEDES, pending_new, pending_old, "pe")
    with pytest.raises(GraphStoreUnavailableError):  # crash between UoW 1 and UoW 2
        await env.accept_assertion(CommitFailingFactory(env.uow, fail_on=2)).handle(
            accept_assertion_command(pending_effect, "pe-acc", actor=USER)
        )
    stored_new = await env.seed_accepted("sn")
    stored_old = await env.seed_accepted("so")
    await env.seed_accepted_assertion(SUPERSEDES, stored_new, stored_old, "ss")
    retracted = await env.seed_accepted("rt", project="acme")
    await env.retract_knowledge().handle(retract_knowledge_command(retracted, "rt-1"))
    experience = await env.capture_experience()
    catalog = await env.seed_catalog_entry()
    accepted_assertion = await env.seed_accepted_assertion(
        SUPPORTS, experience, authoritative, "sa", project="acme"
    )
    order = (
        proposed,
        authoritative,
        revised,
        pending_old,
        stored_old,
        retracted,
        experience,
        catalog,
        accepted_assertion,
    )

    states = await env.get_review_states.handle(
        GetReviewStatesQuery(space_key=SPACE_KEY, record_ids=order)
    )

    assert [state.record_id for state in states] == [r.value for r in order]
    # (record_type, status, effective_status, authority, head_revision)
    expected = [
        ("knowledge", "proposed", "proposed", "proposed", 1),
        ("knowledge", "accepted", "accepted", "authoritative", 1),
        ("knowledge", "accepted", "accepted", "authoritative", 2),
        ("knowledge", "accepted", "superseded", "superseded", 1),
        ("knowledge", "superseded", "superseded", "superseded", 1),
        ("knowledge", "retracted", "retracted", "retracted", 1),
        ("experience", None, None, "not_reviewable", None),
        ("catalog_entry", None, None, "not_reviewable", None),
        ("assertion", "accepted", "accepted", "authoritative", None),
    ]
    assert [
        (s.record_type, s.status, s.effective_status, s.authority, s.head_revision) for s in states
    ] == expected
    by_id = {state.record_id: state for state in states}
    pending = by_id[pending_old.value]
    assert pending.superseded_by_assertion_id == pending_effect.value
    assert tuple(pending.superseded_by_record_ids) == (pending_new.value,)
    assert by_id[proposed.value].decided_by_kind is None
    assert by_id[proposed.value].decided_at is None
    assert by_id[proposed.value].project_key == "acme"
    assert by_id[authoritative.value].decided_by_kind == "user"
    assert by_id[authoritative.value].decided_at
    assert tuple(by_id[authoritative.value].superseded_by_record_ids) == ()
    assert by_id[authoritative.value].superseded_by_assertion_id is None
    assert by_id[authoritative.value].tags == ()

    for state in states:
        contract = RecordReviewStateContract.model_validate(state.model_dump())
        assert contract.contract_version == 1
        assert "accepted_revision" not in RecordReviewStateContract.model_fields
        assert "drifted" not in RecordReviewStateContract.model_fields
        assert RecordReviewStateContract.model_validate_json(contract.model_dump_json()) == contract
        assert contract.record_id == state.record_id
        assert contract.authority == state.authority


# --- AC-021 -------------------------------------------------------------------------------------


async def test_ac021_assertions_by_subjects(review_env: ReviewNeo4jEnv) -> None:
    env = review_env
    k1 = await env.capture("k1", project="acme", title="K1")
    k2 = await env.capture("k2", project="acme", title="K2")
    k3 = await env.capture("k3", project="acme", title="K3")
    c1 = await env.seed_catalog_entry()
    evidence = await env.capture_experience()
    a1 = await env.seed_accepted_assertion(RECOMMENDS, k1, c1, "a1", project="acme")
    a2 = await env.propose(SUPPORTS, k1, k2, "a2", project="acme")
    a3 = await env.propose(RECOMMENDS, k2, k3, "a3", project="acme", evidence=(evidence,))
    a4 = await env.propose(RECOMMENDS, k3, c1, "a4", project="acme")
    await env.retract_assertion().handle(
        retract_assertion_command(a4, "a4-ret", reason="not wanted")
    )

    wanted = await env.list_assertions_by_subjects.handle(
        ListAssertionsBySubjectsQuery(
            space_key=SPACE_KEY,
            subject_ids=(k1, k2),
            predicates=(RECOMMENDS,),
            statuses=(RecordStatusEnum.ACCEPTED, RecordStatusEnum.PROPOSED),
        )
    )
    retracted = await env.list_assertions_by_subjects.handle(
        ListAssertionsBySubjectsQuery(
            space_key=SPACE_KEY, subject_ids=(k3,), statuses=(RecordStatusEnum.RETRACTED,)
        )
    )
    nothing = await env.list_assertions_by_subjects.handle(
        ListAssertionsBySubjectsQuery(space_key=SPACE_KEY, subject_ids=())
    )

    assert {s.assertion_id for s in wanted} == {a1.value, a3.value}
    assert a2.value not in {s.assertion_id for s in wanted}
    by_id = {s.assertion_id: s for s in wanted}
    first, third = by_id[a1.value], by_id[a3.value]
    assert (first.object_type, third.object_type) == ("catalog_entry", "knowledge")
    assert (first.subject_at_revision, first.object_at_revision) == (1, None)
    assert (third.subject_at_revision, third.object_at_revision) == (1, 1)
    assert tuple(third.evidence_ids) == (evidence.value,)
    assert tuple(first.evidence_ids) == ()
    assert first.project_key == third.project_key == "acme"
    assert (first.status, third.status) == ("accepted", "proposed")
    assert [s.assertion_id for s in retracted] == [a4.value]
    assert nothing == []
    for summary in (*wanted, *retracted):
        contract = AssertionSummaryContract.model_validate(summary.model_dump())
        assert contract.contract_version == 1
        assert AssertionSummaryContract.model_validate_json(contract.model_dump_json()) == contract
