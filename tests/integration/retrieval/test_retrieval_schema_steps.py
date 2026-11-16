"""AC-028: the C5a schema steps are required, applied once and idempotent."""

import pytest
from tests.support.knowledge_cli_support import run_json, use_store
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, node_counts, query

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

ALL_STEPS = ["core", "review", "change_feed", "knowledge_fulltext", "retrieval_index", "catalog"]
NEW_STEPS = ["change_feed", "knowledge_fulltext", "retrieval_index"]
INIT_STEPS = ["review", *NEW_STEPS, "catalog"]


def _schema(settings: Neo4jConnectionSettings) -> tuple[list[object], list[object], list[object]]:
    meta = query(settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps")
    constraints = query(
        settings,
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
        "RETURN name, type, labelsOrTypes, properties ORDER BY name",
    )
    indexes = query(
        settings,
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, options "
        "RETURN name, type, labelsOrTypes, properties, options ORDER BY name",
    )
    return list(meta), list(constraints), list(indexes)


def test_ac028(
    core_only_env: Neo4jKnowledgeEnv,
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A store initialised with `core` only refuses `search` and `index sync`, then `store init` fixes it."""
    use_store(monkeypatch, neo4j_settings)

    for argv in (["search", "x"], ["index", "sync"]):
        code, envelope = run_json(capsys, argv)

        assert code == 1, argv
        error = envelope["error"]
        assert error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"  # type: ignore[index]
        assert error["metadata"]["missing_steps"] == NEW_STEPS  # type: ignore[index]
    assert "IndexCursor" not in node_counts(neo4j_settings)

    code, first = run_json(capsys, ["store", "init"])
    after_first = _schema(neo4j_settings)
    code_again, second = run_json(capsys, ["store", "init"])
    after_second = _schema(neo4j_settings)

    assert code == code_again == 0
    assert first["result"]["applied_steps"] == INIT_STEPS  # type: ignore[index]
    assert first["result"]["already_applied_steps"] == ["core"]  # type: ignore[index]
    assert second["result"]["applied_steps"] == []  # type: ignore[index]
    assert after_first[0] == [{"steps": ALL_STEPS}]
    assert after_second == after_first
    index_names = {row["name"] for row in after_first[2]}  # type: ignore[index]
    assert "knowledge_fulltext" in index_names
    constrained = {
        (row["labelsOrTypes"][0], row["properties"][0])  # type: ignore[index]
        for row in after_first[1]
    }
    assert {
        ("Change", "change_key"),
        ("ChangeCounter", "space_id"),
        ("IndexCursor", "cursor_key"),
    } <= constrained
