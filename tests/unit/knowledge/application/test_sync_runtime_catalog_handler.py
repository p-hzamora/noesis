"""SyncRuntimeCatalogHandler: the decision per probed artifact (FR-003, NFR-006, AC-002, AC-003)."""

import pytest
from tests.support.catalog_support import (
    CLAUDE,
    CODEX,
    SKILL,
    CatalogEnv,
    FakeRuntimeInventoryProbe,
    artifact,
    digest_of,
    inventory_of,
    make_catalog_env,
    register_command,
    sync_command,
    unreadable,
)

from noesis.bounded_context.knowledge.application.dtos import SyncReportDto
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogOriginEnum,
    SourceKindEnum,
)
from noesis.exceptions import GraphStoreUnavailableError, StoreNotInitialisedError

pytestmark = pytest.mark.unit

NAME = "plug:helper"


def _skill(
    digest_seed: str = "v1",
    *,
    name: str = NAME,
    description: str | None = "Helps with things",
    version: str | None = "1.0",
    requires: tuple[str, ...] = (),
):
    return artifact(
        "skill",
        name,
        version,
        description=description,
        digest=digest_of(digest_seed),
        requires=requires,
    )


def _entry(env: CatalogEnv, name: str = NAME) -> CatalogEntry:
    return next(e for e in env.catalog.entries.values() if e.name.value == name)


async def _sync(env: CatalogEnv, *probes: FakeRuntimeInventoryProbe, **options: object):
    return await env.syncer(*probes).handle(sync_command(*(p.runtime for p in probes), **options))  # type: ignore[arg-type]


def _block(report: SyncReportDto, index: int = 0):
    return report.runtimes[index]


async def test_unknown_artifact_is_registered_as_discovered_with_manifest_provenance() -> None:
    env = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(
        inventory_of(CLAUDE, _skill(requires=("cli_tool:uv", "bad ref", f"skill:{NAME}")))
    )

    report = await _sync(env, probe)

    block = _block(report)
    assert [(e.kind.value, e.name) for e in block.registered] == [("skill", NAME)]
    assert block.registered[0].manifest_digest == digest_of("v1")
    head = _entry(env).head
    assert head.origin is CatalogOriginEnum.DISCOVERED
    assert head.manifest_digest is not None and head.manifest_digest.value == digest_of("v1")
    assert head.purpose == "Helps with things"
    assert head.location == f"claude-code:{NAME}"
    assert head.version == "1.0"
    assert [p.as_text() for p in head.prerequisites] == ["cli_tool:uv"]
    sources = [s for s in env.store.sources.values() if s.kind is SourceKindEnum.MANIFEST]
    assert [(s.locator, s.digest.value if s.digest else None) for s in sources] == [
        (f"claude-code:{NAME}", digest_of("v1"))
    ]


async def test_missing_description_registers_a_placeholder_purpose() -> None:
    env = await make_catalog_env()

    await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill(description=None))))

    assert _entry(env).head.purpose == "(no description)"


async def test_second_sync_with_unchanged_runtime_writes_nothing() -> None:
    env = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            _skill(),
            artifact("agent", "plug:scout", description="Scouts", digest=digest_of("a1")),
        )
    )
    await _sync(env, probe)
    before = env.state()

    report = await _sync(env, probe)

    assert env.state() == before
    block = _block(report)
    assert (block.registered, block.revised, block.unchanged) == ((), (), 2)


async def test_changed_digest_revises_with_the_new_content() -> None:
    env = await make_catalog_env()
    await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill())))

    report = await _sync(
        env,
        FakeRuntimeInventoryProbe(
            inventory_of(CLAUDE, _skill("v2", description="New words", version="2.0"))
        ),
    )

    assert [(e.name, e.revision) for e in _block(report).revised] == [(NAME, 2)]
    entry = _entry(env)
    assert entry.head_number == 2
    assert (entry.head.purpose, entry.head.version) == ("New words", "2.0")
    assert entry.head.manifest_digest is not None
    assert entry.head.manifest_digest.value == digest_of("v2")
    assert entry.head.origin is CatalogOriginEnum.DISCOVERED


async def test_changed_description_with_same_digest_value_is_not_possible_but_version_change_revises() -> (
    None
):
    env = await make_catalog_env()
    await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill())))

    report = await _sync(
        env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill(version="1.1")))
    )

    assert [e.name for e in _block(report).revised] == [NAME]


async def test_removed_artifact_is_reported_not_installed_and_the_entry_stays() -> None:
    env = await make_catalog_env()
    await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill())))
    before = env.state()

    report = await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE)))

    assert [(n.kind.value, n.name) for n in _block(report).not_installed] == [("skill", NAME)]
    assert env.state() == before


async def test_unreadable_kind_does_not_report_its_entries_as_not_installed() -> None:
    env = await make_catalog_env()
    await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill())))

    report = await _sync(
        env,
        FakeRuntimeInventoryProbe(
            inventory_of(CLAUDE, unreadable_kinds=(unreadable("skill", "probe_failed"),))
        ),
    )

    assert _block(report).not_installed == ()


async def test_invalid_name_and_unreadable_manifest_are_skipped_with_a_reason() -> None:
    env = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(
        inventory_of(
            CLAUDE,
            artifact("skill", "has space", digest=digest_of("x")),
            artifact("skill", "plug:nodigest"),
        )
    )

    report = await _sync(env, probe)

    assert {(s.name, s.reason) for s in _block(report).skipped} == {
        ("has space", "invalid_name"),
        ("plug:nodigest", "manifest_unreadable"),
    }
    assert env.catalog.entries == {}


async def test_dry_run_reports_the_same_without_writing() -> None:
    env = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill()))
    before = env.state()

    report = await _sync(env, probe, dry_run=True)

    assert env.state() == before
    assert report.dry_run
    registered = _block(report).registered[0]
    assert (registered.entry_id, registered.revision) == (None, None)
    assert any("without --dry-run" in step for step in report.next_steps)


async def test_hand_registered_entry_keeps_its_origin_and_prerequisites_on_revise() -> None:
    env = await make_catalog_env()
    await env.register.handle(
        register_command(
            kind=SKILL,
            name=NAME,
            purpose="Curated purpose",
            prerequisites=("cli_tool:gh",),
            location="plug@market",
        )
    )

    report = await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill())))

    assert [e.name for e in _block(report).revised] == [NAME]
    head = _entry(env).head
    assert head.origin is CatalogOriginEnum.REGISTERED
    assert [p.as_text() for p in head.prerequisites] == ["cli_tool:gh"]
    assert head.location == "plug@market"


async def test_two_runtimes_with_different_copies_make_one_entry_and_stay_idempotent() -> None:
    env = await make_catalog_env()
    claude = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill("claude-copy")))
    codex = FakeRuntimeInventoryProbe(inventory_of(CODEX, _skill("codex-copy")))

    first = await _sync(env, claude, codex)
    after_first = env.state()
    second = await _sync(env, claude, codex)

    assert len(env.catalog.entries) == 1
    assert [len(b.registered) for b in first.runtimes] == [1, 0]
    assert env.state() == after_first
    assert [len(b.revised) for b in second.runtimes] == [0, 0]


async def test_store_must_have_the_catalog_step() -> None:
    env = await make_catalog_env(steps=("core",))

    with pytest.raises(StoreNotInitialisedError):
        await _sync(env, FakeRuntimeInventoryProbe(inventory_of(CLAUDE)))


async def test_unreachable_store_is_reported_before_any_probe() -> None:
    from tests.support.catalog_support import UnreachableCatalogReadRepository

    env = await make_catalog_env()
    probe = FakeRuntimeInventoryProbe(inventory_of(CLAUDE, _skill()))
    handler = env.syncer(probe)
    handler._read_repository = UnreachableCatalogReadRepository()

    with pytest.raises(GraphStoreUnavailableError):
        await handler.handle(sync_command(CLAUDE))

    assert probe.calls == 0
