"""AC-004: a search never returns a record of another space."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import (
    OTHER_SPACE_KEY,
    add_space,
    build_searcher,
    capture_experience,
    capture_knowledge,
    hit_ids,
    search_request,
    space_id_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac004_each_space_finds_only_its_own_records(env: Neo4jKnowledgeEnv) -> None:
    """Both spaces hold matching records citing the same commit; each search sees one space."""
    space_s: str = await space_id_of(env)
    space_t: str = await add_space(env)
    in_s = await capture_knowledge(env, "s1", "ports and adapters in S")
    exp_s = await capture_experience(env, "s2", "ports failure seen in S")
    in_t = await capture_knowledge(env, "t1", "ports and adapters in T", space_key=OTHER_SPACE_KEY)
    exp_t = await capture_experience(
        env, "t2", "ports failure seen in T", space_key=OTHER_SPACE_KEY
    )
    searcher = build_searcher(env)

    result_s = await searcher.search(search_request("ports", space_s, all_projects=True))
    result_t = await searcher.search(search_request("ports", space_t, all_projects=True))

    assert set(hit_ids(result_s)) == {in_s, exp_s}
    assert set(hit_ids(result_t)) == {in_t, exp_t}


async def test_ac004_the_project_filter_does_not_leak_records_across_spaces(
    env: Neo4jKnowledgeEnv,
) -> None:
    """Same project key in two spaces: the scope names this space's project only."""
    space_s: str = await space_id_of(env)
    await add_space(env)
    mine = await capture_knowledge(env, "s1", "ports in S", project="acme")
    await capture_knowledge(env, "t1", "ports in T", project="acme", space_key=OTHER_SPACE_KEY)

    result = await build_searcher(env).search(search_request("ports", space_s, project_key="acme"))

    assert hit_ids(result) == [mine]
