"""`noesis catalog ...` as real child processes against the pinned Neo4j container (C6).

Cross-process level of AC-001..AC-011, AC-014 and the e2e rows of "Edge and failure cases" in
`90-verification.md`. AC-013 (change feed) is deferred until C5a merges and has no test.
Every folder is a temporary one (`tests/support/catalog_process_support.py`); every child gets an
explicit minimal environment, so `no_session` holds unless a test sets a marker.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from tests.support.catalog_process_support import (
    CatalogWorld,
    add_installed_skill,
    add_project_skill,
    blocks,
    check_argv,
    corrupt_claude_registry,
    count_label,
    down_environment,
    file_snapshot,
    graph_counts,
    install_claude_plugin,
    install_codex_plugin,
    ledger_keys,
    list_argv,
    make_world,
    register_argv,
    revise_argv,
    run_catalog,
    scan_argv,
    show_argv,
    space_id_of,
    start_catalog,
    world_environment,
    write_tool,
)
from tests.support.knowledge_neo4j_support import make_neo4j_env, query
from tests.support.noesis_process_support import ProcessResult, finish

from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

PLUGIN_SKILL = "python-suite:ddd-interface-cli"
INSTALLED_SKILL = "python-suite:ddd-hexagonal-python"
GH_LOCATION = "https://github.com/cli/cli"
BOTH_RUNTIMES = ["claude-code", "codex"]


@pytest.fixture
def world(tmp_path: Path) -> CatalogWorld:
    """The temporary `claude_home`, `codex_home`, `project` and `bin` folders."""
    return make_world(tmp_path / "world")


@pytest.fixture
def env(world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child environment for the wiped container (the `store` fixture without `store init`)."""
    return world_environment(world, neo4j_settings)


@pytest.fixture
def store(world: CatalogWorld, env: dict[str, str]) -> dict[str, str]:
    """`env` after `noesis store init` ran in its own process (steps `core` and `catalog`)."""
    initialised: ProcessResult = run_catalog(world, ["store", "init"], env)
    assert initialised.code == 0, (initialised.stdout, initialised.stderr)
    return env


def _register(world: CatalogWorld, env: dict[str, str], **options: Any) -> ProcessResult:
    return run_catalog(world, register_argv(**options), env)


def _observation(result: ProcessResult, runtime: str) -> dict[str, Any]:
    """The single observation of the block of `runtime`."""
    block = next(block for block in blocks(result) if block["runtime"] == runtime)
    assert len(block["observations"]) == 1, block
    return block["observations"][0]


def _steps(result: ProcessResult) -> list[str]:
    steps: object = result.result["next_steps"]
    assert isinstance(steps, list)
    return [str(step) for step in steps]


def _error_steps(result: ProcessResult) -> list[str]:
    steps: object = result.error["next_steps"]
    assert isinstance(steps, list)
    return [str(step) for step in steps]


def _entry_nodes(settings: Neo4jConnectionSettings) -> list[dict[str, Any]]:
    return query(
        settings,
        "MATCH (n:CatalogEntry) RETURN n.id AS id, n.catalog_key AS key, "
        "n.head_revision AS head ORDER BY n.catalog_key",
    )


# --- AC-001 .. AC-007: availability, nothing stored --------------------------------------------


def test_ac001_uninstalled_skill_is_unavailable(world: CatalogWorld, store: dict[str, str]) -> None:
    install_claude_plugin(
        world, "python-suite", "claude-flow", "2.0.0", skills=["ddd-hexagonal-python"]
    )
    registered = _register(
        world,
        store,
        kind="skill",
        name=PLUGIN_SKILL,
        purpose="CLI delivery",
        location="python-suite@claude-flow",
        key="k1",
    )
    assert registered.code == 0, (registered.stdout, registered.stderr)
    entry_id = registered.result["id"]

    checked = run_catalog(
        world, check_argv(f"skill:{PLUGIN_SKILL}", runtimes=["claude-code"]), store
    )

    assert checked.code == 0, (checked.stdout, checked.stderr)
    assert len(blocks(checked)) == 1
    block = blocks(checked)[0]
    assert block["runtime"] == "claude-code"
    assert block["host"]
    datetime.fromisoformat(block["observed_at"])
    observation = block["observations"][0]
    assert len(block["observations"]) == 1
    assert observation["entry_id"] == entry_id
    assert (observation["status"], observation["reason"]) == ("unavailable", "not_installed")
    assert observation["version_drift"] is None
    assert block["summary"] == {"available": 0, "unavailable": 1, "unknown": 0}
    assert len([step for step in _steps(checked) if "python-suite@claude-flow" in step]) == 1


def test_ac002_installed_skill_becomes_available_and_nothing_is_stored(
    world: CatalogWorld, store: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    install_path = install_claude_plugin(
        world, "python-suite", "claude-flow", "2.0.0", skills=["ddd-hexagonal-python"]
    )
    assert (
        _register(
            world,
            store,
            kind="skill",
            name=PLUGIN_SKILL,
            purpose="CLI delivery",
            location="python-suite@claude-flow",
            key="k1",
        ).code
        == 0
    )
    argv = check_argv(f"skill:{PLUGIN_SKILL}", runtimes=["claude-code"])
    counts_before = graph_counts(neo4j_settings)
    roots = (world.claude_home, world.codex_dir, world.project, world.bin, world.root / "plugins")
    files_before = file_snapshot(*roots)

    first = run_catalog(world, argv, store)
    skill_file = add_installed_skill(install_path, "ddd-interface-cli")
    second = run_catalog(world, argv, store)

    assert (first.code, second.code) == (0, 0), (first.stdout, second.stdout, second.stderr)
    observed = _observation(second, "claude-code")
    assert (observed["status"], observed["reason"]) == ("available", "none")
    assert observed["observed_version"] == "2.0.0"
    assert observed["version_drift"] is None
    first_at = blocks(first)[0]["observed_at"]
    second_at = blocks(second)[0]["observed_at"]
    assert datetime.fromisoformat(second_at) > datetime.fromisoformat(first_at)
    assert graph_counts(neo4j_settings) == counts_before
    files_after = file_snapshot(*roots)
    assert set(files_after) - set(files_before) == {str(skill_file)}
    assert {path: files_after[path] for path in files_before} == files_before
    for path in world.home.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert first_at.encode() not in content, path
            assert second_at.encode() not in content, path


def test_ac003_runtime_blocks_differ(world: CatalogWorld, store: dict[str, str]) -> None:
    install_codex_plugin(world, "demo-plugin", "demo-market", "1.0.0", skills=["demo-skill"])
    assert _register(world, store, kind="skill", name="demo-plugin:demo-skill", key="k1").code == 0

    checked = run_catalog(
        world,
        check_argv("skill:demo-plugin:demo-skill", runtimes=BOTH_RUNTIMES),
        store,
    )

    assert checked.code == 0, (checked.stdout, checked.stderr)
    assert [block["runtime"] for block in blocks(checked)] == BOTH_RUNTIMES
    claude = _observation(checked, "claude-code")
    codex = _observation(checked, "codex")
    assert (claude["status"], claude["reason"]) == ("unavailable", "not_installed")
    assert (codex["status"], codex["reason"]) == ("available", "none")
    assert codex["observed_version"] == "1.0.0"


def test_ac004_unreadable_registry_gives_probe_failed(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    corrupt_claude_registry(world)
    for kind, name, key in (
        ("skill", INSTALLED_SKILL, "k1"),
        ("agent", "python-suite:ddd-architect", "k2"),
    ):
        assert _register(world, store, kind=kind, name=name, key=key).code == 0

    checked = run_catalog(world, check_argv(runtimes=["claude-code"]), store)

    assert checked.code == 0, (checked.stdout, checked.stderr)
    block = blocks(checked)[0]
    assert [(o["status"], o["reason"]) for o in block["observations"]] == [
        ("unknown", "probe_failed")
    ] * 2
    assert {"kind": "skill", "reason": "probe_failed"} in block["unreadable_kinds"]
    assert {"kind": "agent", "reason": "probe_failed"} in block["unreadable_kinds"]
    assert block["summary"]["unknown"] == 2


def test_ac005_mcp_server_is_not_probed(world: CatalogWorld, store: dict[str, str]) -> None:
    assert _register(world, store, kind="mcp_server", name="docs", key="k1").code == 0

    checked = run_catalog(world, check_argv("mcp_server:docs"), store)

    assert checked.code == 0, (checked.stdout, checked.stderr)
    assert [block["runtime"] for block in blocks(checked)] == BOTH_RUNTIMES
    for block in blocks(checked):
        observation = block["observations"][0]
        assert (observation["status"], observation["reason"]) == ("unknown", "kind_not_probed")
        assert {"kind": "mcp_server", "reason": "kind_not_probed"} in block["unreadable_kinds"]


def test_ac006_missing_cli_prerequisite(world: CatalogWorld, store: dict[str, str]) -> None:
    install_claude_plugin(world, "demo-plugin", "demo-market", "1.0.0", skills=["demo-skill"])
    assert (
        _register(
            world,
            store,
            kind="skill",
            name="demo-plugin:demo-skill",
            requires=["cli_tool:demo-tool"],
            key="k1",
        ).code
        == 0
    )
    argv = check_argv("skill:demo-plugin:demo-skill", runtimes=["claude-code"])

    missing = run_catalog(world, argv, store)
    ran = world.root / "ran"
    write_tool(world, "demo-tool", marker=ran)
    present = run_catalog(world, argv, store)

    before = _observation(missing, "claude-code")
    assert (before["status"], before["reason"]) == ("unavailable", "prerequisite_missing")
    assert before["missing_prerequisites"] == ["cli_tool:demo-tool"]
    after = _observation(present, "claude-code")
    assert (after["status"], after["reason"]) == ("available", "none")
    assert after["missing_prerequisites"] == []
    assert not ran.exists()


def test_ac007_version_drift_keeps_available(world: CatalogWorld, store: dict[str, str]) -> None:
    install_claude_plugin(
        world, "python-suite", "claude-flow", "2.0.1", skills=["ddd-hexagonal-python"]
    )
    assert (
        _register(world, store, kind="skill", name=INSTALLED_SKILL, version="2.0.0", key="k1").code
        == 0
    )

    checked = run_catalog(world, check_argv(runtimes=["claude-code"]), store)

    observation = _observation(checked, "claude-code")
    assert (observation["status"], observation["reason"]) == ("available", "none")
    assert observation["observed_version"] == "2.0.1"
    assert observation["version_drift"] is True
    assert any("noesis catalog revise" in step for step in _steps(checked))


# --- AC-008 .. AC-009: duplicates, idempotency, races ------------------------------------------


def test_ac008_duplicate_and_idempotent_register(
    store: dict[str, str], world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings
) -> None:
    options = {
        "kind": "cli_tool",
        "name": "gh",
        "purpose": "GitHub CLI",
        "location": GH_LOCATION,
    }
    first = _register(world, store, key="k1", **options)
    duplicate = _register(world, store, key="k2", **options)
    replay = _register(world, store, key="k1", **options)
    reused = _register(world, store, key="k1", **{**options, "purpose": "Something else"})

    assert first.code == 0, (first.stdout, first.stderr)
    entry_id = first.result["id"]
    assert first.result["revision"] == 1
    assert duplicate.code == 1
    assert duplicate.error["code"] == "KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS"
    assert any("catalog revise" in step for step in _error_steps(duplicate))
    assert replay.code == 0
    assert (replay.result["id"], replay.result["revision"]) == (entry_id, 1)
    assert reused.code == 1
    assert reused.error["code"] == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"
    space_id = space_id_of(neo4j_settings)
    assert _entry_nodes(neo4j_settings) == [
        {"id": entry_id, "key": f"{space_id}:cli_tool:gh", "head": 1}
    ]
    assert query(
        neo4j_settings,
        "MATCH (:Revision)-[:REVISION_OF]->(e:CatalogEntry) RETURN count(*) AS total",
    ) == [{"total": 1}]
    assert ledger_keys(neo4j_settings) == ["k1"]


@pytest.mark.parametrize("round_number", range(3))
def test_ac009_concurrent_revise_conflict(
    store: dict[str, str],
    world: CatalogWorld,
    neo4j_settings: Neo4jConnectionSettings,
    round_number: int,
) -> None:
    assert (
        _register(world, store, kind="cli_tool", name="gh", location=GH_LOCATION, key="k1").code
        == 0
    )

    def revise(purpose: str, key: str) -> list[str]:
        return revise_argv(
            "cli_tool:gh", key=key, expected=1, purpose=purpose, location=GH_LOCATION
        )

    started = time.monotonic()
    first = start_catalog(world, revise("A", "ka"), store)
    second = start_catalog(world, revise("B", "kb"), store)
    outcomes: list[ProcessResult] = [finish(first, started), finish(second, started)]

    winners = [o for o in outcomes if o.code == 0]
    losers = [o for o in outcomes if o.code == 1]
    assert len(winners) == 1 and len(losers) == 1, [(o.code, o.stdout, o.stderr) for o in outcomes]
    assert winners[0].result["revision"] == 2
    assert losers[0].error["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
    metadata = losers[0].error["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["expected_revision"] == 1 and metadata["actual_revision"] == 2
    winning_purpose = "A" if outcomes[0].code == 0 else "B"
    assert _entry_nodes(neo4j_settings)[0]["head"] == 2
    rows = query(
        neo4j_settings,
        "MATCH (r:Revision)-[:REVISION_OF]->(:CatalogEntry) "
        "RETURN r.number AS number, r.purpose AS purpose ORDER BY r.number",
    )
    assert [row["number"] for row in rows] == [1, 2]
    assert rows[1]["purpose"] == winning_purpose


@pytest.mark.parametrize("round_number", range(3))
def test_two_first_registers_race_yields_one_entry_and_one_already_exists(
    store: dict[str, str],
    world: CatalogWorld,
    neo4j_settings: Neo4jConnectionSettings,
    round_number: int,
) -> None:
    started = time.monotonic()
    first = start_catalog(world, register_argv(kind="cli_tool", name="gh", key="ka"), store)
    second = start_catalog(world, register_argv(kind="cli_tool", name="gh", key="kb"), store)
    outcomes: list[ProcessResult] = [finish(first, started), finish(second, started)]

    winners = [o for o in outcomes if o.code == 0]
    losers = [o for o in outcomes if o.code == 1]
    assert len(winners) == 1 and len(losers) == 1, [(o.code, o.stdout, o.stderr) for o in outcomes]
    assert losers[0].error["code"] == "KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS"
    assert len(_entry_nodes(neo4j_settings)) == 1


# --- AC-010: fail closed ------------------------------------------------------------------------

FAIL_CLOSED_COMMANDS: dict[str, list[str]] = {
    "register": register_argv(
        kind="skill",
        name="x",
        purpose="p",
        location="l",
        key="k",
        sources=["url:https://e.invalid/x"],
    ),
    "revise": revise_argv(
        "skill:x",
        key="k2",
        expected=1,
        purpose="p",
        location="l",
        sources=["url:https://e.invalid/x"],
    ),
    "list": list_argv(),
    "show": show_argv("skill:x"),
    "check": check_argv(),
    "scan": scan_argv(),
}


@pytest.mark.parametrize("command", FAIL_CLOSED_COMMANDS)
def test_ac010_fail_closed_per_command(world: CatalogWorld, command: str) -> None:
    result = run_catalog(world, FAIL_CLOSED_COMMANDS[command], down_environment(world))

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert result.error["next_steps"]


# --- AC-011: scan -------------------------------------------------------------------------------


def test_ac011_scan_lists_uncataloged_and_writes_nothing(
    world: CatalogWorld, store: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    add_project_skill(world, "local-helper")
    registered = _register(
        world,
        store,
        kind="skill",
        name=PLUGIN_SKILL,
        location="python-suite@claude-flow",
        key="k1",
    )
    entry_id = registered.result["id"]
    counts_before = graph_counts(neo4j_settings)

    scanned = run_catalog(world, scan_argv(["claude-code"]), store)

    assert scanned.code == 0, (scanned.stdout, scanned.stderr)
    block = blocks(scanned)[0]
    assert block["runtime"] == "claude-code"
    assert {"kind": "skill", "name": "local-helper", "observed_version": None} in block[
        "uncataloged"
    ]
    assert {
        "entry_id": entry_id,
        "kind": "skill",
        "name": PLUGIN_SKILL,
        "location": "python-suite@claude-flow",
    } in block["not_installed"]
    assert graph_counts(neo4j_settings) == counts_before


# --- AC-014: schema step ------------------------------------------------------------------------


async def test_ac014_core_only_store_rejects_register_until_store_init_adds_catalog(
    world: CatalogWorld, env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    core_only = make_neo4j_env(neo4j_settings)
    try:
        await core_only.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=Key(value="e2e"))
        )
    finally:
        await core_only.client.close()

    rejected = _register(world, env, kind="cli_tool", name="gh", key="k1")

    assert rejected.code == 1, (rejected.stdout, rejected.stderr)
    assert rejected.error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert "catalog" in str(rejected.error["message"]) + str(rejected.error["metadata"])
    assert any("noesis store init" in step for step in _error_steps(rejected))
    assert count_label(neo4j_settings, "CatalogEntry") == 0

    for _ in range(2):
        assert run_catalog(world, ["store", "init"], env).code == 0
    registered = _register(world, env, kind="cli_tool", name="gh", key="k2")

    assert registered.code == 0, (registered.stdout, registered.stderr)
    assert query(neo4j_settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps") == [
        {
            "steps": [
                "core",
                "review",
                "change_feed",
                "knowledge_fulltext",
                "retrieval_index",
                "retrieval_semantic",
                "catalog",
                "catalog_discovery",
                "catalog_fulltext",
                "links",
                "consolidation",
            ]
        }
    ]
    constraints = [
        row
        for row in query(neo4j_settings, "SHOW CONSTRAINTS")
        if row["labelsOrTypes"] == ["CatalogEntry"]
    ]
    assert [(row["type"], row["properties"]) for row in constraints] == [
        ("UNIQUENESS", ["catalog_key"])
    ]
    node = query(
        neo4j_settings,
        "MATCH (n:CatalogEntry) RETURN labels(n) AS labels, keys(n) AS keys",
    )[0]
    assert set(node["labels"]) == {"Record", "CatalogEntry"}
    assert {"id", "space_id", "catalog_key"} <= set(node["keys"])


# --- edge rows ----------------------------------------------------------------------------------


def test_an_entry_of_another_space_is_not_found_and_not_listed(
    world: CatalogWorld, store: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    registered = _register(world, store, kind="cli_tool", name="gh", location=GH_LOCATION, key="k1")
    entry_id = str(registered.result["id"])
    other = {**store, "NOESIS_KNOWLEDGE_SPACE": "other"}
    assert run_catalog(world, ["store", "init"], other).code == 0

    listed = run_catalog(world, list_argv(), other)
    by_key = run_catalog(world, show_argv("cli_tool:gh"), other)
    by_id = run_catalog(world, show_argv(entry_id), other)

    assert listed.code == 0 and listed.result["entries"] == []
    for shown in (by_key, by_id):
        assert shown.code == 1, (shown.stdout, shown.stderr)
        assert shown.error["code"] == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
        assert any("catalog list" in step for step in _error_steps(shown))


def test_check_of_an_unknown_ref_is_not_found(world: CatalogWorld, store: dict[str, str]) -> None:
    result = run_catalog(world, check_argv("skill:nope"), store)

    assert result.code == 1
    assert result.error["code"] == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"


def test_register_with_an_invalid_name_writes_nothing(
    world: CatalogWorld, store: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    result = _register(world, store, kind="skill", name="Bad Name!", key="k1")

    assert result.code == 1
    assert result.error["code"] == "KNOWLEDGE_061_INVALID_CATALOG_NAME"
    assert count_label(neo4j_settings, "CatalogEntry") == 0


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(register_argv(kind="skill", name="x", key=None), id="no-idempotency-key"),
        pytest.param(register_argv(kind="skill", name="x", key="k", sources=()), id="no-source"),
        pytest.param(register_argv(kind="tool", name="x", key="k"), id="kind-tool"),
        pytest.param(
            register_argv(kind="skill", name="x", key="k", purpose=""), id="empty-purpose"
        ),
        pytest.param(
            register_argv(kind="skill", name="x", key="k", location=""), id="empty-location"
        ),
        pytest.param(revise_argv("skill:x", key="k", expected="x"), id="expected-not-integer"),
        pytest.param(revise_argv("skill:x", key="k", expected=None), id="no-expected-revision"),
        pytest.param(revise_argv("skill:x", key="k", purpose=""), id="revise-empty-purpose"),
        pytest.param(revise_argv("skill:x", key="k", location=""), id="revise-empty-location"),
        pytest.param(revise_argv("skill:x", key="k", sources=()), id="revise-no-source"),
        pytest.param(check_argv(runtimes=["vscode"]), id="check-runtime-vscode"),
        pytest.param(scan_argv(["vscode"]), id="scan-runtime-vscode"),
        pytest.param(check_argv(kind="tool"), id="check-kind-tool"),
    ],
)
def test_usage_errors_exit_2_before_any_io(world: CatalogWorld, argv: list[str]) -> None:
    """With the store down, exit 2 and no `INTEGRATION_103` prove nothing was read."""
    env = down_environment(world, NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS="30")

    result = run_catalog(world, argv, env, json_output=False)

    assert result.code == 2, (result.stdout, result.stderr)
    assert "INTEGRATION_103" not in result.stdout + result.stderr
    assert "No such command" not in result.stderr  # exit 2 must come from the option checks
    assert result.seconds < 20


def test_a_missing_config_folder_gives_probe_failed(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    missing = {**store, "CLAUDE_CONFIG_DIR": str(world.root / "no-such-claude-home")}
    for kind, name, key in (("skill", "local", "k1"), ("agent", "reviewer", "k2")):
        assert _register(world, missing, kind=kind, name=name, key=key).code == 0

    checked = run_catalog(world, check_argv(runtimes=["claude-code"]), missing)

    assert checked.code == 0, (checked.stdout, checked.stderr)
    block = blocks(checked)[0]
    assert [(o["status"], o["reason"]) for o in block["observations"]] == [
        ("unknown", "probe_failed")
    ] * 2
    assert {item["kind"] for item in block["unreadable_kinds"]} >= {"skill", "agent"}


@pytest.mark.parametrize(
    ("markers", "expected"),
    [
        pytest.param({}, BOTH_RUNTIMES, id="no-session"),
        pytest.param({"CODEX_THREAD_ID": "t"}, ["codex"], id="codex-thread"),
        pytest.param({"CODEX_SESSION_ID": "t"}, ["codex"], id="codex-session"),
        pytest.param({"NOESIS_SESSION_ID": "s"}, BOTH_RUNTIMES, id="noesis-session-only"),
        pytest.param({"CLAUDECODE": "1"}, ["claude-code"], id="claude-code-marker"),
    ],
)
def test_runtime_resolution_follows_the_session_markers(
    world: CatalogWorld, store: dict[str, str], markers: dict[str, str], expected: list[str]
) -> None:
    checked = run_catalog(world, check_argv(), {**store, **markers})

    assert checked.code == 0, (checked.stdout, checked.stderr)
    assert [block["runtime"] for block in blocks(checked)] == expected


def test_scan_with_an_unreadable_registry_reports_the_kinds_and_no_plugin_artifacts(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    install_claude_plugin(world, "python-suite", "claude-flow", "2.0.0", skills=["a-skill"])
    corrupt_claude_registry(world)

    scanned = run_catalog(world, scan_argv(["claude-code"]), store)

    assert scanned.code == 0, (scanned.stdout, scanned.stderr)
    block = blocks(scanned)[0]
    assert {item["kind"] for item in block["unreadable_kinds"]} >= {"skill", "agent"}
    assert not [item for item in block["uncataloged"] if item["name"].startswith("python-suite:")]


def test_check_on_an_empty_catalog_returns_empty_blocks(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    checked = run_catalog(world, check_argv(), store)

    assert checked.code == 0, (checked.stdout, checked.stderr)
    assert [block["runtime"] for block in blocks(checked)] == BOTH_RUNTIMES
    for block in blocks(checked):
        assert block["observations"] == []
        assert block["summary"] == {"available": 0, "unavailable": 0, "unknown": 0}


def test_record_get_returns_a_catalog_entry_by_id(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    registered = _register(world, store, kind="cli_tool", name="gh", location=GH_LOCATION, key="k1")

    fetched = run_catalog(world, ["record", "get", str(registered.result["id"])], store)

    assert fetched.code == 0, (fetched.stdout, fetched.stderr)
    assert fetched.result["type"] == "catalog_entry"
    assert fetched.result["id"] == registered.result["id"]


def test_list_filters_by_kind_and_name_prefix(world: CatalogWorld, store: dict[str, str]) -> None:
    for kind, name, key in (
        ("cli_tool", "gh", "k1"),
        ("cli_tool", "git", "k2"),
        ("skill", "gh-skill", "k3"),
    ):
        assert _register(world, store, kind=kind, name=name, key=key).code == 0

    def names(argv: list[str]) -> list[str]:
        return sorted(entry["name"] for entry in run_catalog(world, argv, store).result["entries"])  # type: ignore[attr-defined]

    assert names(list_argv()) == ["gh", "gh-skill", "git"]
    assert names(list_argv(kind="cli_tool")) == ["gh", "git"]
    assert names(list_argv(name_prefix="gh")) == ["gh", "gh-skill"]
    assert names(list_argv(kind="cli_tool", name_prefix="gh")) == ["gh"]


def test_show_returns_the_requested_revision_and_a_missing_revision_is_not_found(
    world: CatalogWorld, store: dict[str, str]
) -> None:
    assert (
        _register(
            world, store, kind="cli_tool", name="gh", purpose="P", location=GH_LOCATION, key="k1"
        ).code
        == 0
    )
    assert (
        run_catalog(
            world, revise_argv("cli_tool:gh", key="k2", expected=1, purpose="P2"), store
        ).code
        == 0
    )

    head = run_catalog(world, show_argv("cli_tool:gh"), store).result
    first = run_catalog(world, show_argv("cli_tool:gh", revision=1), store).result
    missing = run_catalog(world, show_argv("cli_tool:gh", revision=9), store)

    assert (head["number"], head["purpose"], head["head_revision"]) == (2, "P2", 2)
    assert (first["number"], first["purpose"], first["head_revision"]) == (1, "P", 2)
    assert len(first["sources"]) == 1
    assert missing.code == 1
    assert missing.error["code"] == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"


# --- Q-009: partial revise ----------------------------------------------------------------------


def test_partial_revise_keeps_omitted_values_clears_by_empty_string_and_noops_write_nothing(
    world: CatalogWorld, store: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    registered = _register(
        world,
        store,
        kind="cli_tool",
        name="gh",
        purpose="P",
        version="1.0",
        requires=["cli_tool:git"],
        location=GH_LOCATION,
        key="k1",
    )
    assert registered.code == 0, (registered.stdout, registered.stderr)

    def revise(key: str, expected: int, **content: Any) -> ProcessResult:
        return run_catalog(
            world, revise_argv("cli_tool:gh", key=key, expected=expected, **content), store
        )

    def head() -> dict[str, Any]:
        return run_catalog(world, show_argv("cli_tool:gh"), store).result

    purpose_only = revise("k2", 1, purpose="P2")
    assert purpose_only.code == 0 and purpose_only.result["revision"] == 2
    assert head()["purpose"] == "P2"
    assert head()["declared_version"] == "1.0"
    assert head()["prerequisites"] == ["cli_tool:git"]
    assert head()["location"] == GH_LOCATION

    assert revise("k3", 2, version="").result["revision"] == 3
    assert head()["declared_version"] is None
    assert revise("k4", 3, requires=[""]).result["revision"] == 4
    assert head()["prerequisites"] == []
    assert revise("k5", 4, requires=["cli_tool:a", "cli_tool:b"]).result["revision"] == 5
    assert head()["prerequisites"] == ["cli_tool:a", "cli_tool:b"]
    revisions_before = count_label(neo4j_settings, "Revision")
    ledger_before = ledger_keys(neo4j_settings)

    noop = revise("k6", 5, purpose="P2", requires=["cli_tool:a", "cli_tool:b"])
    stale_noop = revise("k7", 4, purpose="P2", requires=["cli_tool:a", "cli_tool:b"])

    assert noop.code == 0, (noop.stdout, noop.stderr)
    assert noop.result["revision"] == 5
    assert count_label(neo4j_settings, "Revision") == revisions_before
    assert ledger_keys(neo4j_settings) == ledger_before
    assert "k6" not in ledger_keys(neo4j_settings)
    assert stale_noop.code == 1
    assert stale_noop.error["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
