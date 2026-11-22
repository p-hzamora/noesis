"""`noesis search` as real processes: AC-006, AC-026 (absent) and AC-027 (default project)."""

from pathlib import Path

import pytest
from tests.support.git_support import add_worktree, init_repo, isolate_git
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.noesis_process_support import (
    ProcessResult,
    capture_command,
    run_noesis,
)
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge
from tests.support.retrieval.retrieval_process_support import (
    closed_store_environment,
    run_noesis_in,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


def _ids(result: ProcessResult) -> set[str]:
    return {str(hit["id"]) for hit in result.result["hits"]}  # type: ignore[attr-defined]


def test_ac006_a_capture_is_found_by_search_in_the_next_process(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str]
) -> None:
    """Lexical immediacy: no sync, no cursor; the full-text index answers the next process."""
    captured = run_noesis(
        capture_command("ac006", title="Zanzibar routing", body="Prefer zanzibar routing."),
        child_env,
    )
    assert captured.code == 0, captured.stdout
    record_id = str(captured.result["record_id"])

    found = run_noesis(["search", "zanzibar", "--project", "demo"], child_env)

    assert found.code == 0, found.stdout
    assert [hit["id"] for hit in found.result["hits"]] == [record_id]  # type: ignore[attr-defined]
    hit = found.result["hits"][0]  # type: ignore[index]
    assert (hit["type"], hit["revision"], hit["status"], hit["authority"]) == (
        "knowledge",
        1,
        "proposed",
        "proposed",
    )
    assert hit["rank"] == 1
    assert hit["sources"] == ["lexical"]
    assert found.result["index"]["stale_hits"] == 0  # type: ignore[index]


def test_ac026_absent(env: Neo4jKnowledgeEnv, child_env: dict[str, str]) -> None:
    """Production wiring registers no semantic source: state `absent`, and `--require-semantic` fails."""
    assert (
        run_noesis(capture_command("ac026", title="Ports guide", body="ports"), child_env).code == 0
    )

    plain = run_noesis(["search", "ports", "--all-projects"], child_env)
    strict = run_noesis(["search", "ports", "--all-projects", "--require-semantic"], child_env)

    assert plain.code == 0, plain.stdout
    assert plain.result["hits"]
    assert plain.result["index"]["semantic"]["state"] == "absent"  # type: ignore[index]
    assert plain.result["index"]["pending_changes"] == 0  # type: ignore[index]
    assert strict.code == 1
    assert strict.error["code"] == "RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE"


async def test_ac027_default_project(
    env: Neo4jKnowledgeEnv,
    neo4j_settings: Neo4jConnectionSettings,
    child_env: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The working directory picks the project: a repository, its linked worktree, none, or unknown."""
    isolate_git(monkeypatch)
    ka = await capture_knowledge(env, "ka", "layout of acme", project="acme")
    ko = await capture_knowledge(env, "ko", "layout of other", project="other")
    kg = await capture_knowledge(env, "kg", "layout everywhere")
    projects_before = query(neo4j_settings, "MATCH (p:Project) RETURN count(p) AS total")
    repos = tmp_path / "repos"
    acme = init_repo(repos / "acme")
    worktree = add_worktree(acme, repos / "acme-wt", "wt")
    plain = repos / "plain"
    plain.mkdir()
    zeta = init_repo(repos / "zeta")

    def search(cwd: Path, *options: str) -> ProcessResult:
        found = run_noesis_in(cwd, ["search", "layout", *options], child_env)
        assert found.code == 0, (found.stdout, found.stderr)
        return found

    for checkout in (acme, worktree):
        found = search(checkout)
        scope = found.result["scope"]
        assert _ids(found) == {ka, kg}
        assert (scope["project"], scope["project_source"], scope["space_wide_only"]) == (  # type: ignore[index]
            "acme",
            "git_root",
            False,
        )
        assert found.result["warnings"] == []

    outside = search(plain)
    scope = outside.result["scope"]
    assert _ids(outside) == {kg}
    assert (scope["project"], scope["project_source"], scope["space_wide_only"]) == (  # type: ignore[index]
        None,
        "none",
        True,
    )
    assert any("not in a git repository" in str(w) for w in outside.result["warnings"])  # type: ignore[attr-defined]

    unknown = search(zeta)
    scope = unknown.result["scope"]
    assert _ids(unknown) == {kg}
    assert (scope["project"], scope["project_source"], scope["space_wide_only"]) == (  # type: ignore[index]
        "zeta",
        "git_root",
        True,
    )
    assert any("project zeta not found in space" in str(w) for w in unknown.result["warnings"])  # type: ignore[attr-defined]

    target = search(zeta, "--target-root", str(worktree))
    assert _ids(target) == {ka, kg}
    assert target.result["scope"]["project_source"] == "target_root"  # type: ignore[index]

    planned = acme / "new-repository"
    fresh = search(acme, "--target-root", str(planned))
    assert _ids(fresh) == {kg}
    assert fresh.result["scope"]["space_wide_only"] is True  # type: ignore[index]
    assert not planned.exists()

    briefing = run_noesis_in(
        acme, ["recall", "layout", "--no-synthesis", "--target-root", str(planned)], child_env
    )
    assert briefing.code == 0, briefing.stdout
    assert {record["id"] for record in briefing.result["records"]} == {kg}  # type: ignore[attr-defined]

    everything = search(acme, "--all-projects")
    assert _ids(everything) == {ka, ko, kg}
    assert everything.result["scope"]["project_source"] == "all_projects"  # type: ignore[index]

    chosen = search(acme, "--project", "other")
    assert _ids(chosen) == {ko, kg}
    assert chosen.result["scope"]["project_source"] == "option"  # type: ignore[index]

    assert query(neo4j_settings, "MATCH (p:Project) RETURN count(p) AS total") == projects_before


def test_ac027_both_project_options_are_a_usage_error_with_no_store_contact(tmp_path: Path) -> None:
    result = run_noesis_in(
        tmp_path,
        ["search", "layout", "--project", "other", "--all-projects"],
        closed_store_environment(tmp_path / "home"),
        json_output=False,
    )

    assert result.code == 2
