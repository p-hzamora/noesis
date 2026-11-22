"""`noesis catalog sync --json` end to end through the CLI against Neo4j (WP-07)."""

from pathlib import Path

import pytest
from tests.support.catalog_process_support import CatalogWorld, install_claude_plugin, make_world
from tests.support.knowledge_cli_support import run_json, use_store
from tests.support.runtime_folders_support import skill_manifest

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


@pytest.fixture
def world(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings, monkeypatch: pytest.MonkeyPatch
) -> CatalogWorld:
    made: CatalogWorld = make_world(tmp_path / "world")
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(made.claude_home))
    monkeypatch.setenv("HOME", str(made.home))
    monkeypatch.chdir(made.project)
    return made


def test_sync_reports_registered_then_unchanged_and_dry_run_writes_nothing(
    world: CatalogWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    path = install_claude_plugin(world, "plug", "market", "1.0", skills=("cli",))
    (path / "skills" / "cli" / "SKILL.md").write_text(skill_manifest("Builds a cli"), "utf-8")
    assert run_json(capsys, ["store", "init"])[0] == 0
    argv = ["catalog", "sync", "--runtime", "claude-code"]

    dry_code, dry = run_json(capsys, [*argv, "--dry-run"])
    code, first = run_json(capsys, argv)
    again_code, second = run_json(capsys, argv)
    listed_code, listed = run_json(capsys, ["catalog", "list"])

    assert (dry_code, code, again_code, listed_code) == (0, 0, 0, 0)
    assert dry["result"]["dry_run"] is True  # type: ignore[index]
    block = first["result"]["runtimes"][0]  # type: ignore[index]
    assert block["runtime"] == "claude-code"
    assert [(e["kind"], e["name"]) for e in block["registered"]] == [("skill", "plug:cli")]
    assert block["registered"][0]["manifest_digest"].startswith("sha256:")
    assert first["result"]["dry_run"] is False  # type: ignore[index]
    again = second["result"]["runtimes"][0]  # type: ignore[index]
    assert (again["registered"], again["revised"], again["unchanged"]) == ([], [], 1)
    entries = listed["result"]["entries"]  # type: ignore[index]
    assert [(e["name"], e["origin"]) for e in entries] == [("plug:cli", "discovered")]
