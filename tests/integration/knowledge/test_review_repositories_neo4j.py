"""Assertion and review persistence against the pinned Neo4j container.

Covers the repository round trip (edge cases), AC-007 (deterministic), AC-009 (catalog object on
the `:Record` label), the container part of AC-010 (`live_key`), revise against accept
(deterministic lock) and the decision fields (edge cases).
"""

import asyncio
from typing import Any

import pytest
from tests.support.knowledge_neo4j_support import query
from tests.support.knowledge_support import AGENT, NOW
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    accept_knowledge_command,
    bulk_command,
    propose_command,
    retract_assertion_command,
    retract_knowledge_command,
)
from tests.support.review_support import (
    MIGRATED,
    ReviewNeo4jEnv,
    decisions_of,
    make_review_neo4j_env,
)

from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.domain.entities import Assertion, Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    GraphContent,
    Key,
    RecordId,
    RecordStatusEnum,
    SourceKindEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import DecisionBasisEnum
from noesis.exceptions import (
    DuplicateAssertionError,
    RevisionConflictError,
    StatusConflictError,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

BLOCKED_PROBE_SECONDS: float = 0.5
SUPPORTS = AssertionPredicateEnum.SUPPORTS
RECOMMENDS = AssertionPredicateEnum.RECOMMENDS


async def _space_id(env: ReviewNeo4jEnv) -> SpaceId:
    return SpaceId(value=await env.space_id())


async def test_an_assertion_round_trips_with_its_edges_and_revisions(
    review_env: ReviewNeo4jEnv,
) -> None:
    """An assertion with two evidence ids, two sources, a project and a tag reads back unchanged."""
    subject = await review_env.capture("subject", project="acme")
    evidence_knowledge = await review_env.capture("ev-k", project="acme", title="Evidence")
    evidence_experience = await review_env.capture_experience()
    object_ = await review_env.capture("object", project="acme", title="Object")
    await review_env.capture_experience("exp-2")  # a bystander the assertion must not touch
    sources = (
        NewSourceInput(kind=SourceKindEnum.COMMIT, locator="b" * 40),
        NewSourceInput(kind=SourceKindEnum.AGENT_SESSION, locator="s-77"),
    )
    command = propose_command(
        SUPPORTS,
        subject,
        object_,
        "p-round",
        evidence=(evidence_knowledge, evidence_experience),
        project="acme",
        tags=("lang:python",),
        sources=sources,
    )

    proposed = await review_env.propose_assertion().handle(command)

    space_id = await _space_id(review_env)
    async with review_env.uow() as uow:
        stored: Assertion | None = await uow.assertions.get_by_id(
            RecordId(value=proposed.id), space_id=space_id
        )
    assert stored is not None
    assert stored.predicate is SUPPORTS
    assert (stored.subject_id, stored.object_id) == (subject, object_)
    assert set(stored.evidence_ids) == {evidence_knowledge, evidence_experience}
    assert stored.rationale == command.rationale
    assert stored.status is RecordStatusEnum.PROPOSED
    assert (stored.subject_at_revision, stored.object_at_revision) == (1, 1)
    assert [tag.value for tag in stored.applicability.tags] == ["lang:python"]
    assert stored.applicability.project_id is not None
    assert len(stored.source_ids) == 2

    settings = review_env.settings
    node = query(
        settings,
        "MATCH (a:Record:Assertion {id: $id}) RETURN labels(a) AS labels, properties(a) AS props",
        id=proposed.id,
    )[0]
    assert {"Record", "Assertion"} <= set(node["labels"])
    assert node["props"]["space_id"] == space_id.value
    assert node["props"]["predicate"] == "supports"
    assert node["props"]["status"] == "proposed"
    assert node["props"]["tags"] == ["lang:python"]
    assert node["props"]["live_key"]
    edges = query(
        settings,
        "MATCH (a:Assertion {id: $id})-[e]->(t) "
        "RETURN type(e) AS type, t.id AS target, e.at_revision AS at_revision",
        id=proposed.id,
    )
    by_type: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        by_type.setdefault(edge["type"], []).append(edge)
    assert [(e["target"], e["at_revision"]) for e in by_type["SUBJECT"]] == [(subject.value, 1)]
    assert [(e["target"], e["at_revision"]) for e in by_type["OBJECT"]] == [(object_.value, 1)]
    assert {e["target"] for e in by_type["EVIDENCED_BY"]} == {
        evidence_knowledge.value,
        evidence_experience.value,
    }
    assert len(by_type["FROM_SOURCE"]) == 2
    assert len(by_type["BELONGS_TO_PROJECT"]) == 1
    assert len(by_type["IN_SPACE"]) == 1

    record = await review_env.base.get_record.handle(
        GetRecordQuery(
            space_key=Key(value="default"), record_id=RecordId(value=proposed.id), revision=None
        )
    )
    assert record.type == "assertion"
    assert record.predicate == "supports"
    assert record.rationale == command.rationale
    assert record.status == "proposed"


async def test_ac009_catalog_object_on_record_label(review_env: ReviewNeo4jEnv) -> None:
    """A bare `:Record:CatalogEntry {id, space_id}` node is accepted as a `recommends` object."""
    subject = await review_env.seed_accepted("k", project="acme")
    catalog = await review_env.seed_catalog_entry()

    proposed = await review_env.propose_assertion().handle(
        propose_command(RECOMMENDS, subject, catalog, "p-cat", project="acme")
    )

    assert proposed.status == "proposed"
    assert proposed.object_id == catalog.value
    assert proposed.object_at_revision is None
    assert proposed.subject_at_revision == 1
    edge = query(
        review_env.settings,
        "MATCH (:Assertion {id: $id})-[e:OBJECT]->(c:CatalogEntry) RETURN c.id AS id, e.at_revision AS rev",
        id=proposed.id,
    )
    assert edge == [{"id": catalog.value, "rev": None}]


async def test_ac010_container_live_key_is_removed_on_retract_and_the_statement_is_freed(
    review_env: ReviewNeo4jEnv,
) -> None:
    """AC-010 container check, and the duplicate is refused while the first is live."""
    k = await review_env.seed_accepted("k", project="acme")
    e = await review_env.capture_experience()
    first = await review_env.propose(SUPPORTS, e, k, "k1", project="acme")
    live_key_of = "MATCH (a:Assertion {id: $id}) RETURN a.live_key AS live_key"
    first_key = query(review_env.settings, live_key_of, id=first.value)[0]["live_key"]
    assert first_key

    with pytest.raises(DuplicateAssertionError) as raised:
        await review_env.propose(SUPPORTS, e, k, "k2", project="acme")
    assert raised.value.metadata["existing_id"] == first.value

    outcome = await review_env.retract_assertion().handle(
        retract_assertion_command(first, "ret-1", reason="dup", actor=AGENT)
    )
    assert outcome.outcome == "rejected"
    assert query(review_env.settings, live_key_of, id=first.value) == [{"live_key": None}]

    second = await review_env.propose(SUPPORTS, e, k, "k3", project="acme")
    assert second != first
    second_key = query(review_env.settings, live_key_of, id=second.value)[0]["live_key"]
    assert second_key == first_key  # the same statement encodes to the same key, now freed


async def test_ac007_decision_key_conflict(review_env: ReviewNeo4jEnv) -> None:
    """Two units of work load decision_seq 0; the second to commit loses on `<id>:1`."""
    record_id = await review_env.capture("k", project="acme")
    space_id = await _space_id(review_env)

    async with review_env.uow() as a, review_env.uow() as b:
        loaded_a: Knowledge | None = await a.knowledge.get(record_id, space_id=space_id)
        loaded_b: Knowledge | None = await b.knowledge.get(record_id, space_id=space_id)
        assert loaded_a is not None and loaded_b is not None
        assert loaded_a.decision_seq == loaded_b.decision_seq == 0
        loaded_a.accept(
            expected_revision=1, actor=USER, reason=None, basis=DecisionBasisEnum.USER, now=NOW
        )
        await a.knowledge.save(loaded_a)
        await a.commit()
        loaded_b.reject(actor=USER, reason="race", basis=DecisionBasisEnum.USER, now=NOW)
        with pytest.raises(StatusConflictError) as raised:
            await b.knowledge.save(loaded_b)
            await b.commit()

    assert raised.value.error_code == "KNOWLEDGE_220_STATUS_CONFLICT"
    decisions = decisions_of(review_env.settings, record_id.value)
    assert [(d["seq"], d["transition"]) for d in decisions] == [(1, "accept")]
    assert query(
        review_env.settings,
        "MATCH (k:Knowledge {id: $id}) RETURN k.status AS status, k.decision_seq AS seq",
        id=record_id.value,
    ) == [{"status": "accepted", "seq": 1}]


async def test_accept_waits_for_a_revise_holding_the_lock_and_then_fails_on_the_new_head(
    review_env: ReviewNeo4jEnv,
) -> None:
    """Revise against accept, deterministic: B's accept waits on A's lock, sees head 2, raises 202."""
    record_id = await review_env.capture("k", project="acme")
    space_id = await _space_id(review_env)
    other: ReviewNeo4jEnv = make_review_neo4j_env(review_env.settings)
    try:
        async with review_env.uow() as holder:
            held: Knowledge | None = await holder.knowledge.get_for_update(
                record_id, space_id=space_id
            )
            assert held is not None
            waiting: asyncio.Task[Any] = asyncio.create_task(
                other.accept_knowledge().handle(
                    accept_knowledge_command(record_id, "b-accept", expected=1, actor=AGENT)
                )
            )
            await asyncio.sleep(BLOCKED_PROBE_SECONDS)
            assert not waiting.done()
            revision = held.revise(
                expected_revision=1,
                actor=AGENT,
                source_ids=held.head.source_ids,
                content=GraphContent(title="Retry policy", body="Revised while locked."),
                now=NOW,
            )
            await holder.knowledge.append_revision(held, revision)
            await holder.commit()

        with pytest.raises(RevisionConflictError) as raised:
            await asyncio.wait_for(waiting, timeout=20)
    finally:
        await other.client.close()

    assert raised.value.metadata["expected_revision"] == 1
    assert raised.value.metadata["actual_revision"] == 2
    assert decisions_of(review_env.settings, record_id.value) == []
    status = query(
        review_env.settings,
        "MATCH (k:Knowledge {id: $id}) RETURN k.status AS status, k.head_revision AS head",
        id=record_id.value,
    )
    assert status == [{"status": "proposed", "head": 2}]


async def test_decision_fields_are_stored_for_every_transition_and_basis(
    review_env: ReviewNeo4jEnv,
) -> None:
    """Accept, reject, retract, supersede and a bulk accept each leave every decision field."""
    settings = review_env.settings
    accepted = await review_env.capture("acc", project="acme")
    await review_env.accept_knowledge().handle(
        accept_knowledge_command(accepted, "acc-1", actor=AGENT, reason="looks right")
    )
    rejected = await review_env.capture("rej", project="acme")
    await review_env.retract_knowledge().handle(
        retract_knowledge_command(rejected, "rej-1", reason="wrong", actor=AGENT)
    )
    retracted = await review_env.seed_accepted("ret", project="acme")
    await review_env.retract_knowledge().handle(
        retract_knowledge_command(retracted, "ret-1", reason="obsolete")
    )
    old = await review_env.seed_accepted("old")
    new = await review_env.seed_accepted("new")
    supersedes = await review_env.propose(AssertionPredicateEnum.SUPERSEDES, new, old, "sup")
    await review_env.accept_assertion().handle(
        accept_assertion_command(supersedes, "sup-acc", actor=USER)
    )
    bulk_record = await review_env.capture("bulk", tags=(MIGRATED,))
    await review_env.bulk_accept().handle(bulk_command(MIGRATED))

    def only(record_id: RecordId) -> dict[str, Any]:
        decisions = decisions_of(settings, record_id.value)
        return decisions[-1]

    accept = only(accepted)
    assert (accept["seq"], accept["transition"]) == (1, "accept")
    assert (accept["from_status"], accept["to_status"]) == ("proposed", "accepted")
    assert accept["actor_kind"] == "agent" and accept["actor_session"] == AGENT.session
    assert accept["basis"] == "agent_project"
    assert accept["pinned_revision"] == 1
    assert accept["reason"] == "looks right"
    assert accept.get("cause_assertion_id") is None
    assert accept["decision_key"] == f"{accepted.value}:1"
    assert accept["decided_at"] is not None

    reject = only(rejected)
    assert (reject["transition"], reject["to_status"]) == ("reject", "retracted")
    assert reject["reason"] == "wrong"
    assert reject.get("pinned_revision") is None and reject.get("cause_assertion_id") is None

    retract = only(retracted)
    assert (retract["seq"], retract["transition"]) == (2, "retract")
    assert (retract["from_status"], retract["to_status"]) == ("accepted", "retracted")
    assert retract["reason"] == "obsolete"
    assert retract["basis"] == "user"
    assert retract["actor_kind"] == "user" and retract.get("actor_session") is None
    assert retract.get("pinned_revision") is None

    supersede = only(old)
    assert (supersede["seq"], supersede["transition"]) == (2, "supersede")
    assert (supersede["from_status"], supersede["to_status"]) == ("accepted", "superseded")
    assert supersede["basis"] == "supersession_effect"
    assert supersede["cause_assertion_id"] == supersedes.value
    assert supersede.get("pinned_revision") is None

    bulk = only(bulk_record)
    assert (bulk["seq"], bulk["transition"], bulk["basis"]) == (1, "accept", "migration")
    assert bulk["reason"] == f"bulk accept: tag {MIGRATED}"
    assert bulk["pinned_revision"] == 1
    for record_id in (accepted, rejected, retracted, old, new, bulk_record):
        for decision in decisions_of(settings, record_id.value):
            assert decision["basis"] != "migration" or record_id == bulk_record
