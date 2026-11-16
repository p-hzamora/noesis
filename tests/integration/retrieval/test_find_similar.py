"""AC-024: `similar` stays inside the active space and keeps every status and project."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.knowledge_support import NOW
from tests.support.retrieval.retrieval_neo4j_support import (
    OTHER_SPACE_KEY,
    add_space,
    build_searcher,
    capture_knowledge,
    space_id_of,
)
from tests.support.retrieval.status_writer import set_status

from noesis.bounded_context.retrieval.application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
    FindSimilarRecordsQuery,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac024_space_only(env: Neo4jKnowledgeEnv) -> None:
    space_id: str = await space_id_of(env)
    await add_space(env)
    anchor = await capture_knowledge(env, "a", "hexagonal ports adapters", project="acme")
    retracted = await capture_knowledge(env, "b", "hexagonal ports", project="other")
    superseded = await capture_knowledge(env, "c", "ports adapters")
    proposed = await capture_knowledge(env, "d", "hexagonal adapters", project="acme")
    foreign = await capture_knowledge(
        env, "x", "hexagonal ports adapters", space_key=OTHER_SPACE_KEY
    )
    for record_id, status in (
        (anchor, "accepted"),
        (retracted, "retracted"),
        (superseded, "superseded"),
    ):
        await set_status(
            env.client, space_id=space_id, record_id=record_id, status=status, occurred_at=NOW
        )

    result = await FindSimilarRecordsHandler(build_searcher(env)).handle(
        FindSimilarRecordsQuery(record_id=anchor, space_id=space_id, limit=10)
    )

    assert {hit.record_id for hit in result.hits} == {retracted, superseded, proposed}
    assert anchor not in {hit.record_id for hit in result.hits}
    assert foreign not in {hit.record_id for hit in result.hits}
    for hit in result.hits:
        assert hit.sources
        assert {str(source) for source in hit.sources} <= {"lexical", "graph"}
    assert [hit.rank for hit in result.hits] == [1, 2, 3]
    labels = {hit.record_id: str(hit.authority) for hit in result.hits}
    assert labels[retracted] == "retracted"
