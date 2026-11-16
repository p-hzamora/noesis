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
