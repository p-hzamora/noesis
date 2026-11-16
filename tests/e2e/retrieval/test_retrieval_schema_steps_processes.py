"""AC-028 across processes: a store without the C5a steps refuses `search` and `index`."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.noesis_process_support import run_noesis

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

NEW_STEPS = ["change_feed", "knowledge_fulltext", "retrieval_index"]
INIT_STEPS = ["review", *NEW_STEPS, "catalog", "links"]


def test_ac028_processes(
    core_only_env: Neo4jKnowledgeEnv,
    child_env: dict[str, str],
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    """Missing steps are named, no cursor is written; a `store init` process applies them once."""
    for argv in (["search", "x"], ["index", "sync"]):
        refused = run_noesis(argv, child_env)

        assert refused.code == 1, argv
        assert refused.error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
        assert refused.error["metadata"] == {"missing_steps": NEW_STEPS}
    assert not query(neo4j_settings, "MATCH (c:IndexCursor) RETURN c")

    first = run_noesis(["store", "init"], child_env)
    second = run_noesis(["store", "init"], child_env)

    assert first.code == second.code == 0
    assert first.result["applied_steps"] == INIT_STEPS
    assert second.result["applied_steps"] == []
    assert run_noesis(["search", "x"], child_env).code == 0
