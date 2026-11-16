"""Q-013: neighbours are Knowledge and Experience records that share a Source with a seed."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import (
    capture_experience,
    capture_knowledge,
    commit_source,
    space_id_of,
)

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SRC_A, SRC_B, SRC_C, SRC_Z = (commit_source(fill) for fill in "abcf")


async def test_neighbours_share_sources_with_seeds_and_exclude_seeds_and_unrelated_records(
    env: Neo4jKnowledgeEnv,
) -> None:
    """S1 cites A,B and S2 cites B,C (so the seeds share B); all records are in one project."""
    space_id: str = await space_id_of(env)
    seed_1 = await capture_knowledge(env, "s1", "seed one", project="acme", sources=(SRC_A, SRC_B))
    seed_2 = await capture_knowledge(env, "s2", "seed two", project="acme", sources=(SRC_B, SRC_C))
    n1 = await capture_knowledge(env, "n1", "near one", project="acme", sources=(SRC_A, SRC_B))
    n2 = await capture_knowledge(env, "n2", "near two", project="acme", sources=(SRC_A,))
    n3 = await capture_knowledge(env, "n3", "near three", project="acme", sources=(SRC_C,))
    unrelated = await capture_knowledge(
        env, "z", "same project, no shared source", project="acme", sources=(SRC_Z,)
    )
    experience = await capture_experience(env, "e", "saw it fail", sources=(SRC_A,))

    found = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [seed_1, seed_2], space_id=space_id, limit=50
    )

    pairs = {(item.record_id, item.seed_id): item.shared_sources for item in found}
    assert pairs == {
        (n1, seed_1): 2,
        (n1, seed_2): 1,
        (n2, seed_1): 1,
        (n3, seed_2): 1,
        (experience, seed_1): 1,
    }
    assert unrelated not in {item.record_id for item in found}
    assert {seed_1, seed_2}.isdisjoint({item.record_id for item in found})
    assert {(item.relation, item.distance) for item in found} == {("shared_source", 1)}
    assert all(item.contract_version == 1 for item in found)


async def test_limit_ranks_neighbours_by_the_sum_of_sources_shared_with_each_seed(
    env: Neo4jKnowledgeEnv,
) -> None:
    """One Source shared with two seeds (sum 2) outranks one Source shared with one seed (sum 1)."""
    space_id: str = await space_id_of(env)
    seed_1 = await capture_knowledge(env, "s1", "seed one", sources=(SRC_A, SRC_B))
    seed_2 = await capture_knowledge(env, "s2", "seed two", sources=(SRC_B,))
    single = await capture_knowledge(env, "n1", "one seed, one source", sources=(SRC_A,))
    both = await capture_knowledge(env, "n2", "two seeds, one source", sources=(SRC_B,))

    found = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [seed_1, seed_2], space_id=space_id, limit=1
    )

    assert {item.record_id for item in found} == {both}
    assert single not in {item.record_id for item in found}
