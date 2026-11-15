"""CatalogAvailabilityInboundAdapter (FR-011, NFR-001; AC-012 a and c, Q-006 and Q-010 defaults)."""

import pytest
from tests.support.catalog_support import (
    CLAUDE,
    CODEX,
    SKILL,
    CatalogEnv,
    FakeHostToolProbe,
    FakeRuntimeInventoryProbe,
    UnreachableCatalogReadRepository,
    artifact,
    inventory_of,
    make_catalog_env,
    register_command,
    unreadable,
)
from tests.support.knowledge_support import NOW

from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.catalog_availability_inbound_adapter import (
    CatalogAvailabilityInboundAdapter,
)
from noesis.exceptions import CatalogEntryNotFoundError, GraphStoreUnavailableError
from noesis.shared_kernel.contracts.knowledge import (
    CatalogAvailabilityRequestContract,
    CatalogAvailabilityResultContract,
)

pytestmark = pytest.mark.unit


def request(
    env: CatalogEnv, entry_ids: list[str], runtimes: list[str]
) -> CatalogAvailabilityRequestContract:
    return CatalogAvailabilityRequestContract(
        space_id=env.space_id.value, entry_ids=entry_ids, runtimes=runtimes
    )


async def register_skill(env: CatalogEnv, name: str, **overrides: object) -> str:
    result = await env.register.handle(
        register_command(f"k-{name}", kind=SKILL, name=name, location="p@m", **overrides)
    )
    return result.id


async def test_ac012_adapter_raises_store_failure() -> None:
    """AC-012 (a): the store error reaches the caller unchanged, with no result and no probe."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register_skill(env, "demo")
    claude, codex = (FakeRuntimeInventoryProbe(inventory_of(r)) for r in (CLAUDE, CODEX))
    host = FakeHostToolProbe(())
    adapter = CatalogAvailabilityInboundAdapter(
        check=env.checker(
            claude, codex, host_tools=host, read_repository=UnreachableCatalogReadRepository()
        )
    )

    with pytest.raises(GraphStoreUnavailableError) as error:
        await adapter.check(request(env, [entry_id], ["claude-code", "codex"]))

    assert error.value.error_code == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert (claude.calls, codex.calls, host.calls) == (0, 0, 0)


async def test_ac012_probe_level_problem_is_a_checked_result_with_unknown_entries() -> None:
    """AC-012 (c)."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register_skill(env, "demo")
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, unreadable_kinds=(unreadable("skill", "probe_failed"),))
    )
    adapter = CatalogAvailabilityInboundAdapter(check=env.checker(probe))

    result: CatalogAvailabilityResultContract = await adapter.check(
        request(env, [entry_id], ["claude-code"])
    )

    assert result.outcome == "checked"
    assert result.reason_code is None
    (block,) = result.runtimes
    (entry,) = block.entries
    assert (entry.entry_id, entry.status, entry.reason) == (entry_id, "unknown", "probe_failed")


async def test_adapter_maps_the_report_to_the_result_contract_per_runtime() -> None:
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register_skill(
        env, "demo", version="2.0.0", purpose="Demo skill", prerequisites=("cli_tool:absent",)
    )
    claude = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, artifact("skill", "demo", "2.0.1"), host="box-1")
    )
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX, host="box-1"))
    adapter = CatalogAvailabilityInboundAdapter(check=env.checker(claude, codex))

    result = await adapter.check(request(env, [entry_id], ["codex", "claude-code"]))

    assert result.contract_version == 1
    first, second = result.runtimes
    assert (first.runtime, first.host) == ("codex", "box-1")
    assert (second.runtime, second.host) == ("claude-code", "box-1")
    assert first.observed_at == second.observed_at == "2026-11-14T12:00:00+00:00"
    (codex_entry,) = first.entries
    assert (codex_entry.status, codex_entry.reason) == ("unavailable", "not_installed")
    (claude_entry,) = second.entries
    assert (claude_entry.entry_id, claude_entry.kind, claude_entry.name) == (
        entry_id,
        "skill",
        "demo",
    )
    assert (claude_entry.purpose, claude_entry.declared_version, claude_entry.location) == (
        "Demo skill",
        "2.0.0",
        "p@m",
    )
    assert (claude_entry.status, claude_entry.reason) == ("unavailable", "prerequisite_missing")
    assert claude_entry.observed_version == "2.0.1"
    assert claude_entry.version_drift is None
    assert list(claude_entry.missing_prerequisites) == ["cli_tool:absent"]


async def test_not_checked_when_no_runtime_resolves_without_any_read_or_probe() -> None:
    """Q-006 default."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register_skill(env, "demo")
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    host = FakeHostToolProbe(())
    adapter = CatalogAvailabilityInboundAdapter(check=env.checker(probe, host_tools=host))

    result = await adapter.check(request(env, [entry_id], []))

    assert result.outcome == "not_checked"
    assert result.reason_code == "runtime_unresolved"
    assert list(result.runtimes) == []
    assert (probe.calls, host.calls) == (0, 0)
    assert env.read.calls == []


async def test_an_unknown_entry_id_propagates_as_261_not_as_not_checked() -> None:
    """Q-006 default."""
    env: CatalogEnv = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    adapter = CatalogAvailabilityInboundAdapter(check=env.checker(probe))

    with pytest.raises(CatalogEntryNotFoundError) as error:
        await adapter.check(request(env, ["0" * 25 + "9"], ["claude-code"]))

    assert error.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"
    assert probe.calls == 0


async def test_an_id_from_another_space_is_261_because_the_request_space_binds_the_check() -> None:
    """Q-010 default plus Q-006 default."""
    env: CatalogEnv = await make_catalog_env()
    entry_id = await register_skill(env, "demo")
    other = KnowledgeSpace.create(
        id=env.base.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE))
    adapter = CatalogAvailabilityInboundAdapter(check=env.checker(probe))

    with pytest.raises(CatalogEntryNotFoundError):
        await adapter.check(
            CatalogAvailabilityRequestContract(
                space_id=other.id.value, entry_ids=[entry_id], runtimes=["claude-code"]
            )
        )

    assert probe.calls == 0
