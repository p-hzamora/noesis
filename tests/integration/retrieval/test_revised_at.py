"""AC-021: `revised_at` is the creation time of the head (or requested) revision."""

import json
from pathlib import Path

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import store_environment
from tests.support.retrieval.retrieval_neo4j_support import (
    T1,
    T2,
    T3,
    capture_experience,
    capture_knowledge,
    revise_knowledge,
    space_id_of,
)
from tests.support.retrieval.retrieval_process_support import ACTIVE_SPACE, run_noesis_in

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac021(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings, tmp_path: Path
) -> None:
    """K at T1 revised at T2, Experience E at T3: state, revision contract and CLI hits agree."""
    space_id: str = await space_id_of(env)
    env.clock.current = T1
    knowledge_id: str = await capture_knowledge(env, "k", "layout rules", body="layout v1")
    env.clock.current = T2
    await revise_knowledge(env, knowledge_id, "k-rev", expected=1, body="layout v2")
    env.clock.current = T3
    experience_id: str = await capture_experience(env, "e", "layout failure")

    states = await Neo4jRecordStateReaderAdapter(env.client).get_states(
        [knowledge_id, experience_id], space_id=space_id
    )
    first_revision = await Neo4jIndexableRecordReaderAdapter(env.client).get(
        knowledge_id, 1, space_id=space_id
    )

    revised: dict[str, object] = {state.record_id: state.revised_at for state in states}
    assert revised == {knowledge_id: T2, experience_id: T3}
    assert first_revision.revised_at == T1

    child_home: Path = tmp_path / "child-home"
    found = run_noesis_in(
        child_home,
        ["search", "layout"],
        store_environment(child_home, ACTIVE_SPACE, neo4j_settings),
    )
    assert found.code == 0, found.stdout
    hits = {hit["id"]: hit["revised_at"] for hit in found.result["hits"]}  # type: ignore[index]
    assert hits == {
        knowledge_id: "2026-01-02T00:00:00Z",
        experience_id: "2026-01-03T00:00:00Z",
    }
    assert json.loads(found.stdout)["ok"] is True
