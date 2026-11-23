"""Knowledge publishes current review and live recommends summaries as kernel contracts."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge, space_id_of

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.review_readers_adapter import (
    ReviewReadersAdapter,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_review_and_recommendations_use_current_effective_state(
    env: Neo4jKnowledgeEnv,
) -> None:
    space = await space_id_of(env)
    record = await capture_knowledge(env, "subject", "guidance")
    catalog = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    accepted = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
    retracted = "01ARZ3NDEKTSV4RRFFQ69G5FAX"
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (subject:Record {id: $subject})
        SET subject.status = 'accepted'
        CREATE (catalog:Record:CatalogEntry {id: $catalog, space_id: $space})
        WITH subject, catalog UNWIND [$accepted, $retracted] AS id
        CREATE (a:Record:Assertion {id: id, space_id: $space, subject_id: $subject,
            object_id: $catalog, predicate: 'recommends', status: CASE WHEN id = $accepted THEN 'accepted' ELSE 'retracted' END})
        CREATE (a)-[:SUBJECT {at_revision: 1}]->(subject) CREATE (a)-[:OBJECT]->(catalog)
        """,
            {
                "subject": record,
                "catalog": catalog,
                "space": space,
                "accepted": accepted,
                "retracted": retracted,
            },
        )
        await tx.commit()
    adapter = ReviewReadersAdapter(env.client)
    (state,) = await adapter.get_states([record], space_id=space)
    assert state.authority == "authoritative" and state.head_revision == 1
    (endorsement,) = await adapter.by_subjects([record], space_id=space)
    assert endorsement.assertion_id == accepted and endorsement.subject_at_revision == 1
    assert endorsement.object_type == "catalog_entry"
    assert await adapter.get_states([record], space_id="01ARZ3NDEKTSV4RRFFQ69G5FAZ") == []


async def test_assertions_by_object_carry_the_basis_of_the_latest_decision(
    env: Neo4jKnowledgeEnv,
) -> None:
    space = await space_id_of(env)
    record = await capture_knowledge(env, "refiner", "guidance")
    catalog = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    recommends = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
    undecided = "01ARZ3NDEKTSV4RRFFQ69G5FAX"
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (subject:Record {id: $subject})
        CREATE (catalog:Record:CatalogEntry {id: $catalog, space_id: $space})
        WITH subject, catalog UNWIND [$recommends, $undecided] AS id
        CREATE (a:Record:Assertion {id: id, space_id: $space, subject_id: $subject,
            object_id: $catalog, predicate: CASE WHEN id = $recommends THEN 'recommends' ELSE 'refines' END,
            status: CASE WHEN id = $recommends THEN 'accepted' ELSE 'proposed' END,
            decision_seq: CASE WHEN id = $recommends THEN 2 ELSE 0 END})
        CREATE (a)-[:SUBJECT {at_revision: 1}]->(subject) CREATE (a)-[:OBJECT]->(catalog)
        WITH a WHERE a.id = $recommends
        CREATE (:Decision {decision_key: a.id + ':1', seq: 1, transition: 'accept', basis: 'agent_project', actor_kind: 'agent', decided_at: datetime()})-[:DECIDES]->(a)
        CREATE (:Decision {decision_key: a.id + ':2', seq: 2, transition: 'accept', basis: 'user', actor_kind: 'user', decided_at: datetime()})-[:DECIDES]->(a)
        """,
            {
                "subject": record,
                "catalog": catalog,
                "space": space,
                "recommends": recommends,
                "undecided": undecided,
            },
        )
        await tx.commit()
    adapter = ReviewReadersAdapter(env.client)

    found = await adapter.by_objects(
        [catalog], space_id=space, predicates=("recommends", "refines", "no-such-predicate")
    )
    only_recommends = await adapter.by_objects(
        [catalog], space_id=space, predicates=("recommends",)
    )
    nothing = await adapter.by_objects([catalog], space_id=space, predicates=("no-such-predicate",))

    assert {(a.assertion_id, a.predicate, a.decision_basis) for a in found} == {
        (recommends, "recommends", "user"),
        (undecided, "refines", None),
    }
    assert [a.assertion_id for a in only_recommends] == [recommends]
    assert nothing == []
