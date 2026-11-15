"""ScanRuntimeCatalogHandler (FR-009, FR-012; AC-011 unit part, AC-010 is in the check handler tests)."""

from typing import Any

import pytest
from tests.support.catalog_support import (
    CLAUDE,
    CLI_TOOL,
    CODEX,
    SKILL,
    CatalogEnv,
    FakeHostToolProbe,
    FakeRuntimeInventoryProbe,
    artifact,
    inventory_of,
    make_catalog_env,
    register_command,
    scan_query,
    unreadable,
)
from tests.support.knowledge_support import NOW

from noesis.bounded_context.knowledge.application.dtos import ScanReportDto
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, Key
from noesis.exceptions import SpaceNotFoundError

pytestmark = pytest.mark.unit


async def register(
    env: CatalogEnv,
    name: str,
    *,
    kind: CatalogEntryKindEnum = SKILL,
    location: str = "plugin@market",
    **overrides: object,
) -> str:
    result = await env.register.handle(
        register_command(
            f"key-{kind.value}-{name}", kind=kind, name=name, location=location, **overrides
        )
    )
    return result.id


def blocks(report: ScanReportDto) -> list[dict[str, Any]]:
    return report.model_dump(mode="json")["runtimes"]


async def test_scan_lists_installed_artifacts_without_an_entry_as_uncataloged() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "kept")
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            artifact("skill", "kept", "1.0"),
            artifact("skill", "local-helper"),
            artifact("agent", "kept"),
            artifact("skill", "plug:fresh", "3.0"),
        )
    )

    report = await env.scanner(probe).handle(scan_query())

    (block,) = blocks(report)
    assert block["runtime"] == "claude-code"
    assert block["host"] == "host-1"
    assert block["observed_at"] == "2026-11-14T12:00:00+00:00"
    assert sorted((u["kind"], u["name"], u["observed_version"]) for u in block["uncataloged"]) == [
        ("agent", "kept", None),
        ("skill", "local-helper", None),
        ("skill", "plug:fresh", "3.0"),
    ]


async def test_scan_matches_names_exactly_so_a_qualified_artifact_leaves_a_bare_entry_not_installed() -> (
    None
):
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(env, "demo-skill", location="demo@market")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "demo:demo-skill")))

    (block,) = blocks(await env.scanner(probe).handle(scan_query()))

    assert [(u["kind"], u["name"]) for u in block["uncataloged"]] == [("skill", "demo:demo-skill")]
    assert block["not_installed"] == [
        {"entry_id": entry_id, "kind": "skill", "name": "demo-skill", "location": "demo@market"}
    ]


async def test_scan_lists_not_installed_entries_with_their_location() -> None:
    """AC-011 (unit)."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(
        env, "python-suite:ddd-interface-cli", location="python-suite@claude-flow"
    )
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "local-helper")))

    (block,) = blocks(await env.scanner(probe).handle(scan_query(runtimes=(CLAUDE,))))

    assert block["not_installed"] == [
        {
            "entry_id": entry_id,
            "kind": "skill",
            "name": "python-suite:ddd-interface-cli",
            "location": "python-suite@claude-flow",
        }
    ]
    assert block["uncataloged"] == [
        {"kind": "skill", "name": "local-helper", "observed_version": None}
    ]


async def test_scan_lists_version_drift_only_for_available_entries() -> None:
    env: CatalogEnv = await make_catalog_env()
    drifted = await register(env, "drifted", version="2.0.0")
    await register(env, "same", version="1.0")
    await register(env, "no-declared")
    await register(env, "blocked", version="1.0", prerequisites=("cli_tool:absent",))
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            artifact("skill", "drifted", "2.0.1"),
            artifact("skill", "same", "1.0"),
            artifact("skill", "no-declared", "9"),
            artifact("skill", "blocked", "5.0"),
        )
    )

    (block,) = blocks(await env.scanner(probe).handle(scan_query()))

    assert block["version_drift"] == [
        {
            "entry_id": drifted,
            "kind": "skill",
            "name": "drifted",
            "declared_version": "2.0.0",
            "observed_version": "2.0.1",
        }
    ]
    assert block["not_installed"] == []


async def test_scan_passes_unreadable_kinds_through_and_does_not_call_unknown_entries_missing() -> (
    None
):
    env: CatalogEnv = await make_catalog_env()
    await register(env, "plug:hexagonal")
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            artifact("skill", "local"),
            unreadable_kinds=(unreadable("skill", "probe_failed"),),
        )
    )

    (block,) = blocks(await env.scanner(probe).handle(scan_query()))

    assert block["unreadable_kinds"] == [{"kind": "skill", "reason": "probe_failed"}]
    assert block["not_installed"] == []


async def test_scan_cannot_report_uncataloged_cli_tools_only_cataloged_ones_are_looked_up() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "gh", kind=CLI_TOOL)
    host = FakeHostToolProbe(("gh", "uncataloged-tool"))
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    (block,) = blocks(await env.scanner(probe, host_tools=host).handle(scan_query()))

    assert host.calls == 1
    assert set(host.requests[0]) == {"gh"}
    assert block["uncataloged"] == []
    assert block["not_installed"] == []


async def test_scan_cataloged_cli_tool_missing_on_the_host_is_not_installed() -> None:
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register(env, "gh", kind=CLI_TOOL, location="https://github.com/cli/cli")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    (block,) = blocks(await env.scanner(probe).handle(scan_query()))

    assert [n["entry_id"] for n in block["not_installed"]] == [entry_id]


async def test_scan_gives_one_block_per_runtime_in_the_given_order() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "demo")))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX, artifact("skill", "other")))

    report = await env.scanner(claude, codex).handle(scan_query(runtimes=(CLAUDE, CODEX)))

    first, second = blocks(report)
    assert (first["runtime"], second["runtime"]) == ("claude-code", "codex")
    assert first["not_installed"] == []
    assert [n["name"] for n in second["not_installed"]] == ["demo"]
    assert [u["name"] for u in second["uncataloged"]] == ["other"]


async def test_scan_registers_and_stores_nothing() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    state = env.state()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "local-helper")))

    await env.scanner(probe).handle(scan_query())

    assert env.state() == state
    assert len(env.catalog.entries) == 1


async def test_scan_of_an_empty_catalog_lists_everything_installed_as_uncataloged() -> None:
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, artifact("skill", "a")))

    (block,) = blocks(await env.scanner(probe).handle(scan_query()))

    assert [u["name"] for u in block["uncataloged"]] == ["a"]
    assert (block["not_installed"], block["version_drift"]) == ([], [])


async def test_scan_only_considers_entries_of_its_own_space() -> None:
    env: CatalogEnv = await make_catalog_env()
    await register(env, "demo")
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    (block,) = blocks(await env.scanner(probe).handle(scan_query(space_key=Key(value="other"))))

    assert block["not_installed"] == []


async def test_scan_in_an_unknown_space_fails_before_any_probe() -> None:
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))

    with pytest.raises(SpaceNotFoundError):
        await env.scanner(probe).handle(scan_query(space_key=Key(value="nowhere")))

    assert probe.calls == 0
