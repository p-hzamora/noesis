"""CheckCatalogAvailabilityHandler (FR-004..FR-008, FR-010, NFR-001; AC-001/003/005/006/007/010 unit parts)."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.support.catalog_support import (
    CLAUDE,
    CLI_TOOL,
    CODEX,
    MCP_SERVER,
    SKILL,
    CatalogEnv,
    FakeHostToolProbe,
    FakeRuntimeInventoryProbe,
    UnreachableCatalogReadRepository,
    artifact,
    check_query,
    inventory_of,
    make_catalog_env,
    register_command,
    scan_query,
    unreadable,
)
from tests.support.knowledge_support import NOW

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityReportDto,
)
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    Key,
)
from noesis.exceptions import (
    CatalogEntryNotFoundError,
    GraphStoreUnavailableError,
    SpaceNotFoundError,
)

pytestmark = pytest.mark.unit


async def register(
    env: CatalogEnv,
    name: str,
    *,
    kind: CatalogEntryKindEnum = SKILL,
    location: str = "plugin@market",
    **overrides: object,
) -> str:
    """Register an entry and return its id."""
    result = await env.register.handle(
        register_command(
            f"key-{kind.value}-{name}", kind=kind, name=name, location=location, **overrides
        )
    )
    return result.id


def blocks(report: AvailabilityReportDto) -> list[dict[str, Any]]:
    return report.model_dump(mode="json")["runtimes"]


def observed(block: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {o["name"]: o for o in block["observations"]}


async def test_check_uninstalled_skill_is_unavailable_and_next_steps_name_its_location() -> None:
    """AC-001 (handler level)."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(
        env, "python-suite:ddd-interface-cli", location="python-suite@claude-flow"
    )
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, artifact("skill", "python-suite:ddd-hexagonal-python", "2.0.0"))
    )

    report = await env.checker(probe).handle(
        check_query("skill:python-suite:ddd-interface-cli", runtimes=(CLAUDE,))
    )

    (block,) = blocks(report)
    assert block["runtime"] == "claude-code"
    assert block["host"] == "host-1"
    assert block["observed_at"] == "2026-11-14T12:00:00+00:00"
    (observation,) = block["observations"]
    assert observation["entry_id"] == entry_id
    assert (observation["status"], observation["reason"]) == ("unavailable", "not_installed")
    assert observation["version_drift"] is None
    assert block["summary"] == {"available": 0, "unavailable": 1, "unknown": 0}
    assert sum("python-suite@claude-flow" in step for step in report.next_steps) == 1


async def test_check_names_the_location_of_every_unavailable_entry_only() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "gone-a", location="plugin-a@market")
    await register(env, "gone-b", location="plugin-b@market")
    await register(env, "here", location="plugin-c@market")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "here")))

    report = await env.checker(probe).handle(check_query())

    steps = " ".join(report.next_steps)
    assert "plugin-a@market" in steps
    assert "plugin-b@market" in steps
    assert "plugin-c@market" not in steps


async def test_check_runtime_blocks_differ_per_runtime() -> None:
    """AC-003 (unit): two fake probes give the claude-code / codex split."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo-plugin:demo-skill", location="demo-plugin@demo-market")
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    codex = FakeRuntimeInventoryProbe(
        inventory_of(CODEX, artifact("skill", "demo-plugin:demo-skill", "1.0.0"))
    )

    report = await env.checker(claude, codex).handle(
        check_query("skill:demo-plugin:demo-skill", runtimes=(CLAUDE, CODEX))
    )

    first, second = blocks(report)
    assert [first["runtime"], second["runtime"]] == ["claude-code", "codex"]
    (claude_obs,) = first["observations"]
    (codex_obs,) = second["observations"]
    assert (claude_obs["status"], claude_obs["reason"]) == ("unavailable", "not_installed")
    assert (codex_obs["status"], codex_obs["reason"]) == ("available", "none")
    assert codex_obs["observed_version"] == "1.0.0"
    assert (claude.calls, codex.calls) == (1, 1)


async def test_check_blocks_follow_the_order_of_the_given_runtimes() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, host="claude-host"))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX, host="codex-host"))

    report = await env.checker(claude, codex).handle(check_query(runtimes=(CODEX, CLAUDE)))

    assert [(b["runtime"], b["host"]) for b in blocks(report)] == [
        ("codex", "codex-host"),
        ("claude-code", "claude-host"),
    ]


async def test_check_only_probes_the_requested_runtimes() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX))

    await env.checker(claude, codex).handle(check_query(runtimes=(CODEX,)))

    assert (claude.calls, codex.calls) == (0, 1)


async def test_check_mcp_server_is_unknown_not_probed_in_every_runtime() -> None:
    """AC-005 (unit)."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "docs", kind=MCP_SERVER, location="https://example.invalid/docs")
    not_probed = (unreadable("mcp_server", "kind_not_probed"),)
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, unreadable_kinds=not_probed))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX, unreadable_kinds=not_probed))

    report = await env.checker(claude, codex).handle(
        check_query("mcp_server:docs", runtimes=(CLAUDE, CODEX))
    )

    for block in blocks(report):
        (observation,) = block["observations"]
        assert (observation["status"], observation["reason"]) == ("unknown", "kind_not_probed")
        assert block["unreadable_kinds"] == [{"kind": "mcp_server", "reason": "kind_not_probed"}]
        assert block["summary"] == {"available": 0, "unavailable": 0, "unknown": 1}


async def test_check_codex_agent_entry_is_unknown_not_probed() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo-plugin:reviewer", kind=CatalogEntryKindEnum.AGENT)
    codex = FakeRuntimeInventoryProbe(
        inventory_of(CODEX, unreadable_kinds=(unreadable("agent", "kind_not_probed"),))
    )

    report = await env.checker(codex).handle(check_query(runtimes=(CODEX,)))

    (observation,) = blocks(report)[0]["observations"]
    assert (observation["status"], observation["reason"]) == ("unknown", "kind_not_probed")


async def test_check_unreadable_probe_gives_unknown_probe_failed_and_still_succeeds() -> None:
    """AC-012 (c) at the handler: a probe-level problem is data, not a failure."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "python-suite:ddd-hexagonal-python")
    await register(env, "python-suite:ddd-architect", kind=CatalogEntryKindEnum.AGENT)
    failed = (unreadable("skill", "probe_failed"), unreadable("agent", "probe_failed"))
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, unreadable_kinds=failed))

    report = await env.checker(probe).handle(check_query())

    (block,) = blocks(report)
    assert {(o["status"], o["reason"]) for o in block["observations"]} == {
        ("unknown", "probe_failed")
    }
    assert block["unreadable_kinds"] == [
        {"kind": "skill", "reason": "probe_failed"},
        {"kind": "agent", "reason": "probe_failed"},
    ]
    assert block["summary"]["unknown"] == 2


async def test_check_missing_cli_prerequisite_then_found_on_the_host() -> None:
    """AC-006 (unit): the host probe result is merged into the inventory."""
    env: CatalogEnv = await make_catalog_env()
    await register(
        env, "demo-plugin:demo-skill", prerequisites=("cli_tool:demo-tool",), location="p@m"
    )
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, artifact("skill", "demo-plugin:demo-skill", "1.0.0"))
    )

    missing = await env.checker(probe, host_tools=FakeHostToolProbe(())).handle(
        check_query("skill:demo-plugin:demo-skill")
    )
    found = await env.checker(probe, host_tools=FakeHostToolProbe(("demo-tool",))).handle(
        check_query("skill:demo-plugin:demo-skill")
    )

    (before,) = blocks(missing)[0]["observations"]
    (after,) = blocks(found)[0]["observations"]
    assert (before["status"], before["reason"]) == ("unavailable", "prerequisite_missing")
    assert before["missing_prerequisites"] == ["cli_tool:demo-tool"]
    assert (after["status"], after["reason"]) == ("available", "none")
    assert after["missing_prerequisites"] == []


async def test_check_looks_up_cli_tools_once_for_selected_entries_and_cli_prerequisites() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(
        env, "needs-tools", prerequisites=("cli_tool:x", "skill:other", "mcp_server:docs")
    )
    await register(env, "gh", kind=CLI_TOOL)
    await register(env, "unselected-tool", kind=CLI_TOOL)
    host = FakeHostToolProbe(())
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    await env.checker(probe, host_tools=host).handle(
        check_query("skill:needs-tools", "cli_tool:gh", runtimes=(CLAUDE,))
    )

    assert host.calls == 1
    assert set(host.requests[0]) == {"x", "gh"}


async def test_check_shows_the_same_host_tools_in_every_runtime_block() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "gh", kind=CLI_TOOL, location="https://github.com/cli/cli")
    host = FakeHostToolProbe(("gh",))
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX))

    report = await env.checker(claude, codex, host_tools=host).handle(
        check_query(runtimes=(CLAUDE, CODEX))
    )

    assert host.calls == 1
    for block in blocks(report):
        (observation,) = block["observations"]
        assert (observation["status"], observation["reason"]) == ("available", "none")
        assert observation["observed_version"] is None


async def test_check_version_drift_keeps_the_entry_available_and_points_to_revise() -> None:
    """AC-007 (handler level)."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "python-suite:ddd-hexagonal-python", version="2.0.0")
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, artifact("skill", "python-suite:ddd-hexagonal-python", "2.0.1"))
    )

    report = await env.checker(probe).handle(check_query())

    (observation,) = blocks(report)[0]["observations"]
    assert (observation["status"], observation["reason"]) == ("available", "none")
    assert observation["observed_version"] == "2.0.1"
    assert observation["version_drift"] is True
    assert any("noesis catalog revise" in step for step in report.next_steps)


async def test_check_without_drift_or_unavailability_has_no_install_or_revise_hint() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo", version="1.0", location="plugin@market")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "demo", "1.0")))

    report = await env.checker(probe).handle(check_query())

    assert not any("revise" in s or "plugin@market" in s for s in report.next_steps)


async def test_check_assesses_only_each_entrys_own_prerequisites() -> None:
    """One level deep: A needs B (installed); B needs a missing tool, which only B reports."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "a", prerequisites=("skill:b",))
    await register(env, "b", prerequisites=("cli_tool:absent",))
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, artifact("skill", "a"), artifact("skill", "b"))
    )

    report = await env.checker(probe).handle(check_query())

    by_name = observed(blocks(report)[0])
    assert by_name["a"]["status"] == "available"
    assert (by_name["b"]["status"], by_name["b"]["reason"]) == (
        "unavailable",
        "prerequisite_missing",
    )


async def test_check_prerequisite_of_a_not_probed_kind_is_unknown_not_missing() -> None:
    """Q-011 default."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo", prerequisites=("mcp_server:docs",))
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            artifact("skill", "demo"),
            unreadable_kinds=(unreadable("mcp_server", "kind_not_probed"),),
        )
    )

    report = await env.checker(probe).handle(check_query())

    (observation,) = blocks(report)[0]["observations"]
    assert (observation["status"], observation["reason"]) == ("unknown", "kind_not_probed")
    assert observation["missing_prerequisites"] == []


async def test_check_with_no_refs_covers_every_entry_and_kind_narrows_it() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "s1")
    await register(env, "gh", kind=CLI_TOOL)
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    everything = await env.checker(probe).handle(check_query())
    only_tools = await env.checker(probe).handle(check_query(kind=CLI_TOOL))

    assert set(observed(blocks(everything)[0])) == {"s1", "gh"}
    assert set(observed(blocks(only_tools)[0])) == {"gh"}


async def test_check_refs_select_by_kind_name_or_id_and_kind_narrows_them() -> None:
    env: CatalogEnv = await make_catalog_env()
    skill_id = await register(env, "s1")
    await register(env, "s2")
    await register(env, "gh", kind=CLI_TOOL)
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    selected = await env.checker(probe).handle(check_query(skill_id, "cli_tool:gh"))
    narrowed = await env.checker(probe).handle(check_query(skill_id, "cli_tool:gh", kind=SKILL))

    assert set(observed(blocks(selected)[0])) == {"s1", "gh"}
    assert set(observed(blocks(narrowed)[0])) == {"s1"}


async def test_check_on_an_empty_catalog_gives_empty_blocks_with_zero_counts() -> None:
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    report = await env.checker(probe).handle(check_query())

    (block,) = blocks(report)
    assert block["observations"] == []
    assert block["summary"] == {"available": 0, "unavailable": 0, "unknown": 0}
    assert list(report.next_steps) == []


@pytest.mark.parametrize(
    "refs",
    [
        pytest.param(("skill:nope",), id="only-unknown"),
        pytest.param(("skill:real", "skill:nope"), id="known-and-unknown"),
        pytest.param(("0" * 25 + "9",), id="unknown-id"),
    ],
)
async def test_check_unknown_ref_is_261_and_nothing_is_probed(refs: tuple[str, ...]) -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "real")
    claude, codex = (FakeRuntimeInventoryProbe(inventory_of(r)) for r in (CLAUDE, CODEX))
    host = FakeHostToolProbe(())

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.checker(claude, codex, host_tools=host).handle(
            check_query(*refs, runtimes=(CLAUDE, CODEX))
        )

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert (claude.calls, codex.calls, host.calls) == (0, 0, 0)


async def test_check_entry_of_another_space_is_261_and_nothing_is_probed() -> None:
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(env, "real")
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    with pytest.raises(CatalogEntryNotFoundError):
        await env.checker(probe).handle(check_query(entry_id, space_key=Key(value="other")))

    assert probe.calls == 0


async def test_check_by_space_id_assesses_that_spaces_entries() -> None:
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(env, "demo")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "demo")))

    report = await env.checker(probe).handle(
        check_query(entry_id, space_key=None, space_id=env.space_id)
    )

    (observation,) = blocks(report)[0]["observations"]
    assert observation["entry_id"] == entry_id
    assert observation["status"] == "available"


async def test_check_in_an_unknown_space_fails_before_any_probe() -> None:
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    with pytest.raises(SpaceNotFoundError):
        await env.checker(probe).handle(check_query(space_key=Key(value="nowhere")))

    assert probe.calls == 0


async def test_check_stores_nothing_and_each_run_reports_its_own_observation_time() -> None:
    """AC-002 (unit): observations are computed per invocation and never stored."""
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    state = env.state()
    first = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, observed_at="2026-11-14T12:00:00+00:00"))
    later = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE, artifact("skill", "demo", "2.0.0"), observed_at="2026-11-14T12:05:00+00:00"
        )
    )

    before = await env.checker(first).handle(check_query())
    after = await env.checker(later).handle(check_query())

    (a,), (b,) = (blocks(r)[0]["observations"] for r in (before, after))
    assert (a["status"], a["observed_at"]) == ("unavailable", "2026-11-14T12:00:00+00:00")
    assert (b["status"], b["observed_at"]) == ("available", "2026-11-14T12:05:00+00:00")
    assert b["observed_version"] == "2.0.0"
    assert env.state() == state


def _check(
    env: CatalogEnv, probes: list[FakeRuntimeInventoryProbe], host: FakeHostToolProbe
) -> Callable[[], Any]:
    handler = env.checker(
        *probes, host_tools=host, read_repository=UnreachableCatalogReadRepository()
    )
    return lambda: handler.handle(check_query(runtimes=(CLAUDE, CODEX)))


def _scan(
    env: CatalogEnv, probes: list[FakeRuntimeInventoryProbe], host: FakeHostToolProbe
) -> Callable[[], Any]:
    handler = env.scanner(
        *probes, host_tools=host, read_repository=UnreachableCatalogReadRepository()
    )
    return lambda: handler.handle(scan_query(runtimes=(CLAUDE, CODEX)))


@pytest.mark.parametrize("build", [_check, _scan], ids=["check", "scan"])
async def test_ac010_no_probe_before_store(
    build: Callable[
        [CatalogEnv, list[FakeRuntimeInventoryProbe], FakeHostToolProbe], Callable[[], Any]
    ],
) -> None:
    """AC-010 (unit): when the read repository fails, both runtime probes and the host probe stay at zero calls."""
    env: CatalogEnv = await make_catalog_env()
    probes = [FakeRuntimeInventoryProbe(inventory_of(r)) for r in (CLAUDE, CODEX)]
    host = FakeHostToolProbe(())

    with pytest.raises(GraphStoreUnavailableError) as error:
        await build(env, probes, host)()

    assert error.value.error_code == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert [p.calls for p in probes] == [0, 0]
    assert host.calls == 0


@pytest.mark.parametrize("ref", ["gh", "plugin:x", "not a ref"])
async def test_check_a_ref_that_is_neither_an_id_nor_kind_name_is_261_and_nothing_is_probed(
    ref: str,
) -> None:
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await env.checker(probe).handle(check_query(ref))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert probe.calls == 0
