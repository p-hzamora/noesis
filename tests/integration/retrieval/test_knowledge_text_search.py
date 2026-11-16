"""`30`: Knowledge text search serves head revisions only."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import (
    build_searcher,
    capture_knowledge,
    hit_ids,
    revise_knowledge,
    search_request,
    space_id_of,
)

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_text_search_adapter import (
    Neo4jRecordTextSearchAdapter,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_a_word_only_in_revision_one_finds_nothing_and_counts_no_stale_hit(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id: str = await space_id_of(env)
    record_id: str = await capture_knowledge(
        env, "k", "Retry policy", body="firstrevisionword stays here"
    )
    await revise_knowledge(env, record_id, "k-rev", expected=1, body="secondrevisionword now")
    searcher = build_searcher(env)

    old = await searcher.search(search_request("firstrevisionword", space_id, all_projects=True))
    new = await searcher.search(search_request("secondrevisionword", space_id, all_projects=True))

    assert old.hits == ()
    assert old.stale_hits == 0
    assert hit_ids(new) == [record_id]
    assert new.hits[0].revision == 2


async def test_the_text_search_port_ranks_head_revisions_from_one(env: Neo4jKnowledgeEnv) -> None:
    space_id: str = await space_id_of(env)
    record_id: str = await capture_knowledge(env, "k", "Quokka habitat", body="quokka notes")
    await revise_knowledge(env, record_id, "k-rev", expected=1, body="quokka revised notes")

    hits = await Neo4jRecordTextSearchAdapter(env.client).search(
        "quokka", space_id=space_id, limit=10
    )

    assert [(hit.record_id, hit.revision, hit.rank) for hit in hits] == [(record_id, 2, 1)]
