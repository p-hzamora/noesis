"""Unified `noesis search` as real processes: facets, briefing, compatibility, disclosure, overlay."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.catalog_process_support import (
    CatalogWorld,
    graph_counts,
    install_claude_plugin,
    make_world,
    run_catalog,
    world_environment,
)
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import ProcessResult
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge
from tests.support.retrieval.retrieval_process_support import ACTIVE_SPACE
from tests.support.runtime_folders_support import skill_manifest

from noesis.interfaces.cli.responses import SearchResponse
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

ACTIONS = {"load_skill", "use_agent", "use_cli_tool", "use_mcp_server", "read_record"}
BODY = "Zanzibar bodies stay behind the briefing flag."


@pytest.fixture
def world(tmp_path: Path) -> CatalogWorld:
    return make_world(tmp_path / "world")


@pytest.fixture
def cli_env(world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    return world_environment(world, neo4j_settings, space=ACTIVE_SPACE)


@pytest.fixture
def run(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, cli_env: dict[str, str]
) -> Callable[..., ProcessResult]:
    """Runs `noesis` in the world; the store gets the catalog schema steps first (idempotent)."""
    assert run_catalog(world, ["store", "init"], cli_env).code == 0

    def invoke(*args: str) -> ProcessResult:
        return run_catalog(world, list(args), cli_env)

    return invoke


def _install_and_sync(world: CatalogWorld, run: Callable[..., ProcessResult]) -> None:
    path = install_claude_plugin(
        world, "plug", "market", "1.0", skills=("ddd-interface-cli", "ddd-hexagonal-python")
    )
    manifests = {
        "ddd-interface-cli": "Typer cli delivery for zanzibar tools",
        "ddd-hexagonal-python": "Python ddd foundation",
    }
    for skill, purpose in manifests.items():
        (path / "skills" / skill / "SKILL.md").write_text(skill_manifest(purpose), "utf-8")
    synced = run("catalog", "sync", "--runtime", "claude-code")
    assert synced.code == 0, (synced.stdout, synced.stderr)


def _result(found: ProcessResult) -> dict[str, Any]:
    assert found.code == 0, (found.stdout, found.stderr)
    return found.result  # type: ignore[return-value]


async def test_search_reports_missing_facet(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, run: Callable[..., ProcessResult]
) -> None:
    """AC-005: an unsupported facet is `missing` and no resource is invented for it."""
    _install_and_sync(world, run)

    result = _result(
        run(
            "search",
            "start a project",
            "--need",
            "cli",
            "--need",
            "python-ddd",
            "--need",
            "uv",
            "--runtime",
            "claude-code",
        )
    )

    coverage = {item["id"]: item["coverage"] for item in result["requirements"]}
    assert coverage == {"cli": "covered", "python-ddd": "covered", "uv": "missing"}
    names = [item["name"] for item in result["resources"]]
    assert names == ["plug:ddd-interface-cli", "plug:ddd-hexagonal-python"] or set(names) == {
        "plug:ddd-interface-cli",
        "plug:ddd-hexagonal-python",
    }
    assert {step["action"] for step in result["next_actions"]} <= ACTIONS
    assert all(step["ref"].startswith("catalog:skill:plug:") for step in result["next_actions"])
    assert all(item["available"] == {"claude-code": "available"} for item in result["resources"])


async def test_search_digest_briefing(
    env: Neo4jKnowledgeEnv, run: Callable[..., ProcessResult]
) -> None:
    """`--briefing digest` grounds the matching record without a model call."""
    await capture_knowledge(env, "brief", "Zanzibar routing", body=BODY)

    searched = _result(run("search", "zanzibar", "--briefing", "digest"))

    briefing = searched["briefing"]
    assert briefing is not None
    assert briefing["synthesis"] == "digest"
    assert [record["title"] for record in briefing["records"]] == ["Zanzibar routing"]


async def test_search_json_compat(
    env: Neo4jKnowledgeEnv, run: Callable[..., ProcessResult]
) -> None:
    """AC-009: `--no-resources` keeps exactly the keys the record search always had."""
    await capture_knowledge(env, "compat", "Zanzibar routing", body=BODY)

    old = _result(run("search", "zanzibar", "--all-projects", "--no-resources"))
    new = _result(run("search", "zanzibar", "--all-projects"))

    assert set(old) == set(SearchResponse.model_fields)
    assert set(new) - set(old) >= {"requirements", "resources", "next_actions"}
    assert {key: new[key] for key in old if key not in {"index", "warnings"}} == {
        key: old[key] for key in old if key not in {"index", "warnings"}
    }
    assert set(old["index"]) <= set(new["index"])


async def test_search_progressive_disclosure(
    env: Neo4jKnowledgeEnv, run: Callable[..., ProcessResult]
) -> None:
    """AC-023: no record bodies unless a briefing is requested."""
    await capture_knowledge(env, "disclose", "Zanzibar routing", body=BODY)

    plain = run("search", "zanzibar", "--all-projects")
    briefed = run("search", "zanzibar", "--briefing", "digest")

    assert BODY not in plain.stdout
    assert _result(plain)["briefing"] is None
    assert BODY in briefed.stdout


async def test_search_semantic_absent(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, run: Callable[..., ProcessResult]
) -> None:
    """WP-22: the absent semantic index is a warning; resources are still returned."""
    _install_and_sync(world, run)

    result = _result(run("search", "zanzibar cli", "--need", "cli", "--runtime", "claude-code"))

    assert any("semantic search is absent" in str(w) for w in result["warnings"])
    assert result["resources"]


async def test_search_overlay_cold_start(
    env: Neo4jKnowledgeEnv,
    neo4j_settings: Neo4jConnectionSettings,
    world: CatalogWorld,
    run: Callable[..., ProcessResult],
) -> None:
    """Installed but never synced: found from the overlay, flagged, and nothing is written."""
    path = install_claude_plugin(world, "plug", "market", "1.0", skills=("fresh-cli",))
    (path / "skills" / "fresh-cli" / "SKILL.md").write_text(skill_manifest("A fresh cli"), "utf-8")
    before = graph_counts(neo4j_settings)

    result = _result(run("search", "start", "--need", "cli", "--runtime", "claude-code"))

    (item,) = result["resources"]
    assert item["cataloged"] is False and item["catalog_id"] is None
    assert item["endorsement"] == "none"
    assert item["available"] == {"claude-code": "available"}
    assert result["index"]["catalog"]["unsynced_installed"] == 1
    assert any("noesis catalog sync" in str(w) for w in result["warnings"])
    assert graph_counts(neo4j_settings) == before


async def test_remember_refines_scoped(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, run: Callable[..., ProcessResult]
) -> None:
    """AC-014: a project memory refining a skill shows in `refined_by` only on that project."""
    _install_and_sync(world, run)
    remembered = _result(
        run(
            "remember",
            "--as",
            "knowledge",
            "--subtype",
            "decision",
            "--title",
            "Zanzibar cli exit codes",
            "--body",
            "Zanzibar cli tools exit 2 on usage errors.",
            "--project",
            "demo",
            "--source",
            "commit:" + "b" * 40,
            "--refines",
            "catalog:skill:plug:ddd-interface-cli",
        )
    )
    assert [(item["predicate"], item["status"]) for item in remembered["assertions"]] == [
        ("refines", "proposed")
    ]

    def refined_by(project: str) -> list[dict[str, Any]]:
        result = _result(run("search", "zanzibar cli", "--need", "cli", "--project", project))
        (skill,) = [
            item for item in result["resources"] if item["name"] == "plug:ddd-interface-cli"
        ]
        return list(skill["refined_by"])

    (refinement,) = refined_by("demo")
    assert refinement["ref"].startswith(f"record:{remembered['record_id']}@")
    assert refined_by("other") == []
