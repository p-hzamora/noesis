"""Catalog entries over the real Neo4j adapters (C6: AC-008, AC-012, AC-014, NFR-005, edge rows)."""

import asyncio
import re
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.catalog_process_support import (
    CatalogWorld,
    add_project_skill,
    count_label,
    install_claude_plugin,
    ledger_keys,
    make_world,
    write_tool,
)
from tests.support.knowledge_cli_support import use_closed_store
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env, query
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY, NOW

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
    RuntimeEnum,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryCommand,
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog.check_catalog_availability_handler import (
    CheckCatalogAvailabilityHandler,
    CheckCatalogAvailabilityQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog.list_catalog_entries_handler import (
    ListCatalogEntriesHandler,
    ListCatalogEntriesQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog.scan_runtime_catalog_handler import (
    ScanRuntimeCatalogHandler,
    ScanRuntimeCatalogQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.application.services.secret_redactor import (
    REDACTED,
    SecretRedactor,
)
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    Key,
    SourceKindEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.catalog_availability_inbound_adapter import (
    CatalogAvailabilityInboundAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CATALOG_SCHEMA_STEP,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime import (
    ClaudeCodeRuntimeInventoryAdapter,
    CodexRuntimeInventoryAdapter,
    PathHostToolProbeAdapter,
)
from noesis.core import load_environment
from noesis.exceptions import (
    CatalogEntryAlreadyExistsError,
    CatalogEntryNotFoundError,
    GraphStoreUnavailableError,
    IdempotencyKeyReusedError,
    RevisionConflictError,
    StoreNotInitialisedError,
)
from noesis.interfaces.cli.bootstrap.knowledge_handlers_builder import (
    build_catalog_availability_adapter,
)
from noesis.shared_kernel.contracts.knowledge import CatalogAvailabilityRequestContract
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    Neo4jClient,
    Neo4jConnectionSettings,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

GH: CatalogEntryKindEnum = CatalogEntryKindEnum.CLI_TOOL
GH_LOCATION = "https://github.com/cli/cli"
OTHER_SPACE: Key = Key(value="work")
ALLOWED_REVISION_PROPERTIES: frozenset[str] = frozenset(
    {
        "revision_key",
        "record_id",
        "number",
        "purpose",
        "declared_version",
        "prerequisites",
        "location",
        "source_ids",
        "actor_kind",
        "actor_name",
        "actor_session",
        "created_at",
    }
)


@pytest.fixture
async def catalog_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Real handlers over a store after `store init` with steps `core` and `catalog`."""
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(CATALOG_SCHEMA_STEP,))
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    yield env
    await env.client.close()


@pytest.fixture
async def core_only_env(
    neo4j_settings: Neo4jConnectionSettings,
) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """The `catalog` step is registered but not applied: the store was initialised with `core` only."""
    first: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    try:
        await first.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
    finally:
        await first.client.close()
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(CATALOG_SCHEMA_STEP,))
    yield env
    await env.client.close()


@pytest.fixture
def world(tmp_path: Path) -> CatalogWorld:
    """Temporary `claude_home`, `codex_home`, `project` and `bin` folders."""
    return make_world(tmp_path / "world")


def _source(label: str = "gh") -> NewSourceInput:
    return NewSourceInput(kind=SourceKindEnum.URL, locator=f"https://example.invalid/{label}")


def _register(
    key: str = "k1",
    *,
    kind: CatalogEntryKindEnum = GH,
    name: str = "gh",
    purpose: str = "GitHub CLI",
    version: str | None = None,
    prerequisites: tuple[str, ...] = (),
    location: str = GH_LOCATION,
    space_key: Key = DEFAULT_SPACE_KEY,
) -> RegisterCatalogEntryCommand:
    return RegisterCatalogEntryCommand(
        idempotency_key=key,
        space_key=space_key,
        kind=kind,
        name=name,
        purpose=purpose,
        version=version,
        prerequisites=prerequisites,
        location=location,
        actor=AGENT,
        sources=(_source(name),),
    )


def _revise(ref: str, key: str, purpose: str, *, expected: int = 1) -> ReviseCatalogEntryCommand:
    return ReviseCatalogEntryCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        ref=ref,
        expected_revision=expected,
        purpose=purpose,
        version=None,
        prerequisites=None,
        location=None,
        actor=AGENT,
        sources=(_source(),),
    )


def _register_handler(env: Neo4jKnowledgeEnv) -> RegisterCatalogEntryHandler:
    return RegisterCatalogEntryHandler(
        uow_factory=env.persistence.uow_factory,
        clock=env.clock,
        ids=env.persistence.ids,
        schema=env.persistence.schema,
    )


def _revise_handler(env: Neo4jKnowledgeEnv) -> ReviseCatalogEntryHandler:
    return ReviseCatalogEntryHandler(
        uow_factory=env.persistence.uow_factory,
        clock=env.clock,
        ids=env.persistence.ids,
        schema=env.persistence.schema,
    )


def _list_handler(env: Neo4jKnowledgeEnv) -> ListCatalogEntriesHandler:
    return ListCatalogEntriesHandler(
        read_repository=env.persistence.catalog_read_repository,
        records=env.persistence.read_repository,
        schema=env.persistence.schema,
    )


def _probes(
    env: Neo4jKnowledgeEnv, world: CatalogWorld
) -> tuple[dict[RuntimeEnum, Any], PathHostToolProbeAdapter]:
    host: str = socket.gethostname()
    return (
        {
            RuntimeEnum("claude-code"): ClaudeCodeRuntimeInventoryAdapter(
                config_dir=world.claude_home,
                project_root=world.project,
                clock=env.clock,
                host=host,
            ),
            RuntimeEnum("codex"): CodexRuntimeInventoryAdapter(
                codex_home=world.codex_dir, clock=env.clock, host=host
            ),
        },
        PathHostToolProbeAdapter(path=str(world.bin)),
    )


def _check_handler(env: Neo4jKnowledgeEnv, world: CatalogWorld) -> CheckCatalogAvailabilityHandler:
    runtime_probes, host_tools = _probes(env, world)
    return CheckCatalogAvailabilityHandler(
        read_repository=env.persistence.catalog_read_repository,
        records=env.persistence.read_repository,
        schema=env.persistence.schema,
        runtime_probes=runtime_probes,
        host_tools=host_tools,
    )


async def _space_id(env: Neo4jKnowledgeEnv, key: Key = DEFAULT_SPACE_KEY) -> SpaceId:
    space_id: SpaceId | None = await env.persistence.read_repository.get_space_id(key)
    assert space_id is not None
    return space_id


async def _list(env: Neo4jKnowledgeEnv, space_key: Key = DEFAULT_SPACE_KEY) -> list[Any]:
    listed: Any = await _list_handler(env).handle(ListCatalogEntriesQuery(space_key=space_key))
    return list(listed.entries if hasattr(listed, "entries") else listed)


# --- repository round trip ----------------------------------------------------------------------


async def test_prerequisites_split_on_the_first_colon_and_read_back_equal(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    prerequisites = ("skill:python-suite:ddd-hexagonal-python", "cli_tool:gh")
    await _register_handler(catalog_env).handle(
        _register(
            kind=CatalogEntryKindEnum.SKILL,
            name="python-suite:ddd-interface-cli",
            prerequisites=prerequisites,
        )
    )

    listed = await _list(catalog_env)
    space_id = await _space_id(catalog_env)
    async with catalog_env.uow() as uow:
        entry = await uow.catalog_entries.get_by_key(
            space_id, CatalogEntryKindEnum.SKILL, "python-suite:ddd-interface-cli"
        )

    assert [list(item.prerequisites) for item in listed] == [list(prerequisites)]
    assert entry is not None
    first = entry.head.prerequisites[0]
    assert first.kind is CatalogEntryKindEnum.SKILL
    assert first.name.value == "python-suite:ddd-hexagonal-python"
    assert [ref.as_text() for ref in entry.head.prerequisites] == list(prerequisites)
    assert query(neo4j_settings, "MATCH (r:Revision) RETURN r.prerequisites AS stored") == [
        {"stored": list(prerequisites)}
    ]


async def test_an_entry_and_its_revisions_round_trip_through_the_repository(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await _space_id(catalog_env)
    sources = await catalog_env.references.ensure_sources(space_id, (_source(),))
    entry = CatalogEntry.create(
        id=catalog_env.persistence.ids.new_record_id(),
        space_id=space_id,
        kind=GH,
        name="gh",
        purpose="GitHub CLI",
        version="2.0",
        prerequisites=(CatalogRef.parse("cli_tool:git"),),
        location=GH_LOCATION,
        actor=AGENT,
        source_ids=sources,
        now=NOW,
    )
    entry.collect_events()
    async with catalog_env.uow() as uow:
        await uow.catalog_entries.add(entry)
        await uow.commit()
    async with catalog_env.uow() as uow:
        loaded = await uow.catalog_entries.get_by_key(space_id, GH, "gh")
        by_id = await uow.catalog_entries.get(entry.id, space_id=space_id)
    assert loaded == entry
    assert by_id == entry

    async with catalog_env.uow() as uow:
        locked = await uow.catalog_entries.get_for_update(entry.id, space_id=space_id)
        assert locked is not None
        revision = locked.revise(
            expected_revision=1,
            purpose="GitHub CLI 2",
            version="2.1",
            prerequisites=(),
            location=GH_LOCATION,
            actor=AGENT,
            source_ids=sources,
            now=NOW,
        )
        await uow.catalog_entries.append_revision(locked, revision)
        await uow.commit()
    async with catalog_env.uow() as uow:
        reloaded = await uow.catalog_entries.get_by_key(space_id, GH, "gh")

    assert reloaded is not None
    assert [r.number for r in reloaded.revisions] == [1, 2]
    assert reloaded.head_number == 2
    assert reloaded.revisions[0] == entry.revisions[0]
    assert reloaded.head.purpose == "GitHub CLI 2"
    assert query(neo4j_settings, "MATCH (n:CatalogEntry) RETURN n.head_revision AS head") == [
        {"head": 2}
    ]


async def test_adding_a_second_entry_with_the_same_key_is_already_exists(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await _space_id(catalog_env)
    sources = await catalog_env.references.ensure_sources(space_id, (_source(),))

    def new_entry() -> CatalogEntry:
        return CatalogEntry.create(
            id=catalog_env.persistence.ids.new_record_id(),
            space_id=space_id,
            kind=GH,
            name="gh",
            purpose="GitHub CLI",
            location=GH_LOCATION,
            actor=AGENT,
            source_ids=sources,
            now=NOW,
        )

    async with catalog_env.uow() as uow:
        await uow.catalog_entries.add(new_entry())
        await uow.commit()
    with pytest.raises(CatalogEntryAlreadyExistsError) as raised:
        async with catalog_env.uow() as uow:
            await uow.catalog_entries.add(new_entry())
            await uow.commit()

    assert raised.value.error_code == "KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS"
    assert count_label(neo4j_settings, "CatalogEntry") == 1


async def test_appending_onto_a_stale_head_is_a_revision_conflict(
    catalog_env: Neo4jKnowledgeEnv,
) -> None:
    await _register_handler(catalog_env).handle(_register())
    space_id = await _space_id(catalog_env)

    def revise(entry: CatalogEntry, purpose: str) -> Any:
        return entry.revise(
            expected_revision=1,
            purpose=purpose,
            version=None,
            prerequisites=(),
            location=GH_LOCATION,
            actor=AGENT,
            source_ids=entry.head.source_ids,
            now=NOW,
        )

    async with catalog_env.uow() as uow:
        first = await uow.catalog_entries.get_by_key(space_id, GH, "gh")
        second = await uow.catalog_entries.get_by_key(space_id, GH, "gh")
    assert first is not None and second is not None
    async with catalog_env.uow() as uow:
        await uow.catalog_entries.append_revision(first, revise(first, "First"))
        await uow.commit()
    with pytest.raises(RevisionConflictError) as raised:
        async with catalog_env.uow() as uow:
            await uow.catalog_entries.append_revision(second, revise(second, "Late"))
            await uow.commit()

    assert raised.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert raised.value.metadata["expected_revision"] == 1
    assert raised.value.metadata["actual_revision"] == 2


async def test_two_concurrent_revises_of_one_head_yield_one_winner_and_one_conflict(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    registered = await _register_handler(catalog_env).handle(_register())
    handler = _revise_handler(catalog_env)

    outcomes = await asyncio.gather(
        handler.handle(_revise(registered.id, "ka", "A")),
        handler.handle(_revise(registered.id, "kb", "B")),
        return_exceptions=True,
    )

    conflicts = [o for o in outcomes if isinstance(o, RevisionConflictError)]
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(conflicts) == 1 and len(winners) == 1, outcomes
    assert winners[0].revision == 2
    assert count_label(neo4j_settings, "Revision") == 2


# --- AC-008: store state ------------------------------------------------------------------------


async def test_ac008_duplicate_and_idempotent_register_store_state(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    handler = _register_handler(catalog_env)
    first = await handler.handle(_register("k1"))

    with pytest.raises(CatalogEntryAlreadyExistsError):
        await handler.handle(_register("k2"))
    replay = await handler.handle(_register("k1"))
    with pytest.raises(IdempotencyKeyReusedError):
        await handler.handle(_register("k1", purpose="Something else"))

    assert (first.revision, first.replayed) == (1, False)
    assert (replay.id, replay.revision, replay.replayed) == (first.id, 1, True)
    space_id = (await _space_id(catalog_env)).value
    assert query(
        neo4j_settings, "MATCH (n:CatalogEntry) RETURN n.id AS id, n.catalog_key AS key"
    ) == [{"id": first.id, "key": f"{space_id}:cli_tool:gh"}]
    assert query(
        neo4j_settings, "MATCH (:Revision)-[:REVISION_OF]->(:CatalogEntry) RETURN count(*) AS total"
    ) == [{"total": 1}]
    assert ledger_keys(neo4j_settings) == ["k1"]


# --- AC-014: schema step ------------------------------------------------------------------------


async def test_ac014_catalog_schema_step_and_labels(
    core_only_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    with pytest.raises(StoreNotInitialisedError) as raised:
        await _register_handler(core_only_env).handle(_register())
    assert raised.value.error_code == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert raised.value.metadata["missing_steps"] == ["catalog"]
    assert count_label(neo4j_settings, "CatalogEntry") == 0

    init = InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
    first = await core_only_env.initialise_store.handle(init)
    second = await core_only_env.initialise_store.handle(init)
    assert first.applied_steps == ("catalog",)
    assert second.applied_steps == ()
    assert query(neo4j_settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps") == [
        {"steps": ["core", "catalog"]}
    ]
    constraints = query(neo4j_settings, "SHOW CONSTRAINTS")
    on_entry = [row for row in constraints if row["labelsOrTypes"] == ["CatalogEntry"]]
    assert [(row["type"], row["properties"]) for row in on_entry] == [
        ("UNIQUENESS", ["catalog_key"])
    ]

    await _register_handler(core_only_env).handle(_register())
    node = query(
        neo4j_settings, "MATCH (n:CatalogEntry) RETURN labels(n) AS labels, keys(n) AS keys"
    )[0]
    assert set(node["labels"]) == {"Record", "CatalogEntry"}
    assert {"id", "space_id", "catalog_key"} <= set(node["keys"])


async def test_catalog_reads_on_a_store_without_the_catalog_step_return_nothing(
    core_only_env: Neo4jKnowledgeEnv,
) -> None:
    assert await _list(core_only_env) == []


# --- redaction, names ---------------------------------------------------------------------------


async def test_a_secret_in_the_purpose_is_stored_masked(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    raw = "Deploys with ghp_abcdefghij1234567890ABCD then exits"
    masked, count = SecretRedactor.redact(raw)
    assert count == 1 and REDACTED in masked

    await _register_handler(catalog_env).handle(_register(purpose=raw))

    assert query(neo4j_settings, "MATCH (r:Revision) RETURN r.purpose AS purpose") == [
        {"purpose": masked}
    ]


async def test_names_differing_only_in_case_are_two_entries(
    catalog_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    await _register_handler(catalog_env).handle(_register("k1", name="Gh"))
    await _register_handler(catalog_env).handle(_register("k2", name="gh"))

    rows = query(neo4j_settings, "MATCH (n:CatalogEntry) RETURN n.name AS name ORDER BY n.name")
    assert [row["name"] for row in rows] == ["Gh", "gh"]
    assert sorted(item.name for item in await _list(catalog_env)) == ["Gh", "gh"]


# --- inbound adapter ----------------------------------------------------------------------------


def _request(space_id: str, entry_ids: list[str], runtimes: list[str]) -> Any:
    return CatalogAvailabilityRequestContract(
        contract_version=1, space_id=space_id, entry_ids=entry_ids, runtimes=runtimes
    )


async def test_ac012_adapter_raises_store_failure_on_a_closed_port(
    world: CatalogWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(world.claude_home))
    monkeypatch.setenv("HOME", str(world.home))
    monkeypatch.setenv("PATH", str(world.bin))
    monkeypatch.chdir(world.project)
    environment = load_environment(tmp_path / "absent.env")
    async with Neo4jClient(environment.knowledge.neo4j_connection()) as client:
        adapter = build_catalog_availability_adapter(client, environment)

        with pytest.raises(GraphStoreUnavailableError) as raised:
            await adapter.check(
                _request(
                    "01JD0000000000000000000001",
                    ["01JD0000000000000000000002"],
                    ["claude-code", "codex"],
                )
            )

    assert raised.value.error_code == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


async def test_the_adapter_checks_entries_of_the_requested_space_only(
    catalog_env: Neo4jKnowledgeEnv, world: CatalogWorld
) -> None:
    await catalog_env.initialise_store.handle(InitialiseStoreCommand(default_space_key=OTHER_SPACE))
    registered = await _register_handler(catalog_env).handle(_register())
    adapter = CatalogAvailabilityInboundAdapter(check=_check_handler(catalog_env, world))
    own = (await _space_id(catalog_env)).value
    other = (await _space_id(catalog_env, OTHER_SPACE)).value

    checked = await adapter.check(_request(own, [registered.id], ["claude-code"]))
    with pytest.raises(CatalogEntryNotFoundError) as raised:
        await adapter.check(_request(other, [registered.id], ["claude-code"]))

    assert checked.outcome == "checked" and checked.reason_code is None
    entry = checked.runtimes[0].entries[0]
    assert (entry.entry_id, entry.status, entry.reason) == (
        registered.id,
        "unavailable",
        "not_installed",
    )
    assert raised.value.error_code == "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"


# --- NFR-005 ------------------------------------------------------------------------------------


async def test_stored_revisions_are_runtime_neutral(
    catalog_env: Neo4jKnowledgeEnv,
    neo4j_settings: Neo4jConnectionSettings,
    world: CatalogWorld,
    tmp_path: Path,
) -> None:
    install_claude_plugin(
        world, "python-suite", "claude-flow", "2.0.0", skills=["ddd-hexagonal-python"]
    )
    add_project_skill(world, "local-helper")
    write_tool(world, "gh", marker=world.root / "ran")
    register = _register_handler(catalog_env)
    await register.handle(
        _register(
            "k1",
            kind=CatalogEntryKindEnum.SKILL,
            name="python-suite:ddd-hexagonal-python",
            version="1.0.0",
            location="python-suite@claude-flow",
            prerequisites=("cli_tool:gh",),
        )
    )
    await register.handle(_register("k2"))
    space_id = await _space_id(catalog_env)
    runtimes = (RuntimeEnum("claude-code"), RuntimeEnum("codex"))
    await _check_handler(catalog_env, world).handle(
        CheckCatalogAvailabilityQuery(space_id=space_id, runtimes=runtimes, refs=(), kind=None)
    )
    runtime_probes, host_tools = _probes(catalog_env, world)
    await ScanRuntimeCatalogHandler(
        read_repository=catalog_env.persistence.catalog_read_repository,
        records=catalog_env.persistence.read_repository,
        schema=catalog_env.persistence.schema,
        runtime_probes=runtime_probes,
        host_tools=host_tools,
    ).handle(ScanRuntimeCatalogQuery(space_id=space_id, runtimes=runtimes))

    artifacts: list[InstalledArtifactDto] = [
        *(await runtime_probes[RuntimeEnum("claude-code")].inventory()).artifacts,
        *host_tools.find(("gh",)),
    ]
    install_locations = [str(a.install_location) for a in artifacts if a.install_location]
    assert install_locations, "the fixture must expose at least one install location"
    forbidden = [str(tmp_path), *install_locations]
    hostname = re.compile(rf"(?<![A-Za-z0-9]){re.escape(socket.gethostname())}(?![A-Za-z0-9])")

    nodes = query(
        neo4j_settings,
        "MATCH (n) WHERE n:CatalogEntry OR n:Revision RETURN labels(n) AS labels, "
        "properties(n) AS props",
    )

    assert {tuple(sorted(row["labels"])) for row in nodes} >= {
        ("CatalogEntry", "Record"),
        ("Revision",),
    }
    for row in nodes:
        for name, value in row["props"].items():
            text = str(value)
            assert not any(path in text for path in forbidden), (name, value)
            assert not hostname.search(text), (name, value)
        if "Revision" in row["labels"]:
            assert set(row["props"]) <= ALLOWED_REVISION_PROPERTIES, set(row["props"])
