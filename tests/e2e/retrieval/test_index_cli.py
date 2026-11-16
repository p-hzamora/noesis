"""AC-031: with no projection registered every `index` command is a no-write success."""

from pathlib import Path

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, node_counts
from tests.support.noesis_process_support import run_noesis
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge
from tests.support.retrieval.retrieval_process_support import closed_store_environment

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_ac031_no_projection(
    env: Neo4jKnowledgeEnv,
    child_env: dict[str, str],
    neo4j_settings: Neo4jConnectionSettings,
    tmp_path: Path,
) -> None:
    await capture_knowledge(env, "k", "one record")

    sync = run_noesis(["index", "sync"], child_env)
    rebuild = run_noesis(["index", "rebuild", "--yes"], child_env)
    status = run_noesis(["index", "status", "--verify"], child_env)

    for result in (sync, rebuild, status):
        assert result.code == 0, (result.stdout, result.stderr)
        assert result.result["projections"] == []
        assert result.result["head_sequence"] == 1
        assert any(
            "no index projection registered" in str(warning)
            for warning in result.result["warnings"]  # type: ignore[attr-defined]
        )
    assert status.result["divergences"] == []
    assert not [label for label in node_counts(neo4j_settings) if label.startswith("Index")]

    unregistered = run_noesis(
        ["index", "rebuild", "--projection", "probe", "--yes"],
        closed_store_environment(tmp_path / "closed-home"),
        json_output=False,
    )
    assert unregistered.code == 2
