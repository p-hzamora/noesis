"""`catalog sync` and the resource catalog reader over the real Neo4j adapters (WP-06..WP-09).

AC-001 (cold start overlay), AC-002 / NFR-006 (idempotent sync), AC-003 (removed artifacts stay),
digest change, old-node defaults and cross-space isolation of the `catalog_fulltext` reader.
"""

import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.catalog_process_support import (
    CatalogWorld,
    install_claude_plugin,
    make_world,
)
from tests.support.knowledge_neo4j_support import (
    Neo4jKnowledgeEnv,
    make_neo4j_env,
    node_counts,
    query,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.runtime_folders_support import skill_manifest

from noesis.bounded_context.knowledge.application.dtos import RuntimeEnum, SyncReportDto
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.sync_runtime_catalog_handler import (
    SyncRuntimeCatalogCommand,
    SyncRuntimeCatalogHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogOriginEnum,
    Key,
    SourceKindEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval import (
    Neo4jResourceCatalogReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CATALOG_DISCOVERY_SCHEMA_STEP,
    CATALOG_FULLTEXT_SCHEMA_STEP,
    CATALOG_SCHEMA_STEP,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime import (
    ClaudeCodeRuntimeInventoryAdapter,
    CodexRuntimeInventoryAdapter,
)
from noesis.exceptions import StoreNotInitialisedError
from noesis.shared_kernel.contracts.knowledge import CatalogResourceQueryContract
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

CLAUDE: RuntimeEnum = RuntimeEnum("claude-code")
CODEX: RuntimeEnum = RuntimeEnum("codex")
STEPS = (CATALOG_SCHEMA_STEP, CATALOG_DISCOVERY_SCHEMA_STEP, CATALOG_FULLTEXT_SCHEMA_STEP)
OTHER_SPACE: Key = Key(value="work")


@pytest.fixture
async def env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """A store after `store init` with the catalog, discovery and full-text steps."""
    store: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=STEPS)
    await store.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    await store.initialise_store.handle(InitialiseStoreCommand(default_space_key=OTHER_SPACE))
    query(neo4j_settings, "CALL db.awaitIndexes(30)")
    yield store
    await store.client.close()


@pytest.fixture
def world(tmp_path: Path) -> CatalogWorld:
    return make_world(tmp_path / "world")


def _probes(env: Neo4jKnowledgeEnv, world: CatalogWorld) -> dict[RuntimeEnum, Any]:
    host: str = socket.gethostname()
    return {
        CLAUDE: ClaudeCodeRuntimeInventoryAdapter(
            config_dir=world.claude_home, project_root=world.project, clock=env.clock, host=host
        ),
        CODEX: CodexRuntimeInventoryAdapter(codex_home=world.codex_dir, clock=env.clock, host=host),
    }


def _deps(env: Neo4jKnowledgeEnv) -> dict[str, Any]:
    return {
        "uow_factory": env.persistence.uow_factory,
        "clock": env.clock,
        "ids": env.persistence.ids,
        "schema": env.persistence.schema,
    }


def _syncer(env: Neo4jKnowledgeEnv, world: CatalogWorld) -> SyncRuntimeCatalogHandler:
    return SyncRuntimeCatalogHandler(
        read_repository=env.persistence.catalog_read_repository,
        records=env.persistence.read_repository,
        schema=env.persistence.schema,
        runtime_probes=_probes(env, world),
        register=RegisterCatalogEntryHandler(**_deps(env)),
        revise=ReviseCatalogEntryHandler(**_deps(env)),
    )


async def _sync(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, *, dry_run: bool = False
) -> SyncReportDto:
    return await _syncer(env, world).handle(
        SyncRuntimeCatalogCommand(
            space_key=DEFAULT_SPACE_KEY, runtimes=(CLAUDE,), actor=AGENT, dry_run=dry_run
        )
    )


def _reader(env: Neo4jKnowledgeEnv, world: CatalogWorld) -> Neo4jResourceCatalogReaderAdapter:
    return Neo4jResourceCatalogReaderAdapter(
        env.client, env.persistence.schema, _probes(env, world)
    )


async def _space_id(env: Neo4jKnowledgeEnv, key: Key = DEFAULT_SPACE_KEY) -> str:
    space_id: SpaceId | None = await env.persistence.read_repository.get_space_id(key)
    assert space_id is not None
    return space_id.value


def _install(world: CatalogWorld, *, skills: dict[str, str], agents: tuple[str, ...] = ()) -> Path:
    """Install `plug@market` whose skills carry the given manifests."""
    path: Path = install_claude_plugin(
        world, "plug", "market", "1.0", skills=tuple(skills), agents=agents
    )
    for skill, text in skills.items():
        (path / "skills" / skill / "SKILL.md").write_text(text, encoding="utf-8")
    return path


def _graph_shape(settings: Neo4jConnectionSettings) -> tuple[dict[str, int], int]:
    relationships: int = query(settings, "MATCH ()-[r]->() RETURN count(r) AS total")[0]["total"]
    return node_counts(settings), relationships


async def test_catalog_sync_idempotent(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings
) -> None:
    _install(
        world,
        skills={
            "cli": skill_manifest("Builds a cli", requires=("cli_tool:uv",)),
            "docs": "# plain",
        },
        agents=("scout",),
    )

    first = await _sync(env, world)
    after_first = _graph_shape(neo4j_settings)
    second = await _sync(env, world)

    assert sorted(e.name for e in first.runtimes[0].registered) == [
        "plug:cli",
        "plug:docs",
        "plug:scout",
    ]
    block = second.runtimes[0]
    assert (block.registered, block.revised, block.unchanged) == ((), (), 3)
    assert _graph_shape(neo4j_settings) == after_first
    head = query(
        neo4j_settings,
        "MATCH (r:CatalogRevision {name: 'plug:cli'}) "
        "RETURN r.origin AS origin, r.prerequisites AS prerequisites, r.manifest_digest AS digest",
    )[0]
    assert head["origin"] == CatalogOriginEnum.DISCOVERED.value
    assert head["prerequisites"] == ["cli_tool:uv"]
    assert str(head["digest"]).startswith("sha256:")
    manifests = query(
        neo4j_settings,
        "MATCH (s:Source {kind: $kind}) RETURN s.locator AS locator",
        kind="manifest",
    )
    assert sorted(row["locator"] for row in manifests) == [
        "claude-code:plug:cli",
        "claude-code:plug:docs",
        "claude-code:plug:scout",
    ]


async def test_catalog_sync_keeps_removed(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings
) -> None:
    install_path = _install(world, skills={"cli": skill_manifest("Builds a cli")})
    await _sync(env, world)
    before = _graph_shape(neo4j_settings)
    (install_path / "skills" / "cli" / "SKILL.md").unlink()

    report = await _sync(env, world)

    block = report.runtimes[0]
    assert [(n.kind.value, n.name) for n in block.not_installed] == [("skill", "plug:cli")]
    assert (block.registered, block.revised) == ((), ())
    assert _graph_shape(neo4j_settings) == before


async def test_changed_manifest_revises_and_the_reader_serves_the_new_head(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings
) -> None:
    install_path = _install(world, skills={"cli": skill_manifest("Builds a cli")})
    await _sync(env, world)
    (install_path / "skills" / "cli" / "SKILL.md").write_text(
        skill_manifest("Builds a terminal tool"), encoding="utf-8"
    )

    before_dry = _graph_shape(neo4j_settings)
    dry = await _sync(env, world, dry_run=True)
    counts_after_dry = _graph_shape(neo4j_settings)
    report = await _sync(env, world)
    query(neo4j_settings, "CALL db.awaitIndexes(30)")

    assert [(e.name, e.revision) for e in dry.runtimes[0].revised] == [("plug:cli", None)]
    assert [(e.name, e.revision) for e in report.runtimes[0].revised] == [("plug:cli", 2)]
    assert counts_after_dry == before_dry
    assert _graph_shape(neo4j_settings) != counts_after_dry
    hits = await _reader(env, world).search(
        CatalogResourceQueryContract(space_id=await _space_id(env), terms=("terminal", "builds"))
    )
    assert [(h.name, h.revision, h.cataloged, h.origin) for h in hits] == [
        ("plug:cli", 2, True, "discovered")
    ]


async def test_catalog_overlay_cold_start(env: Neo4jKnowledgeEnv, world: CatalogWorld) -> None:
    _install(
        world,
        skills={
            "cli-builder": skill_manifest(
                "Scaffold a command line project", requires=("cli_tool:uv",)
            ),
            "unrelated": skill_manifest("Waters plants"),
        },
    )
    reader = _reader(env, world)
    space_id = await _space_id(env)

    without = await reader.search(CatalogResourceQueryContract(space_id=space_id, terms=("cli",)))
    hits = await reader.search(
        CatalogResourceQueryContract(
            space_id=space_id,
            terms=("cli", "project"),
            runtimes=("claude-code",),
            include_unsynced=True,
        )
    )

    assert without == []
    assert [(h.name, h.cataloged, h.catalog_id, h.revision) for h in hits] == [
        ("plug:cli-builder", False, None, None)
    ]
    assert hits[0].discovered_runtimes == ("claude-code",)
    assert hits[0].prerequisites == ("cli_tool:uv",)
    assert hits[0].manifest_digest is not None
    assert 0 < hits[0].score <= 1


async def test_overlay_never_writes_and_skips_what_is_cataloged(
    env: Neo4jKnowledgeEnv, world: CatalogWorld, neo4j_settings: Neo4jConnectionSettings
) -> None:
    _install(world, skills={"cli": skill_manifest("Builds a cli")})
    await _sync(env, world)
    _install(
        world,
        skills={"cli": skill_manifest("Builds a cli"), "new-cli": skill_manifest("Another cli")},
    )
    query(neo4j_settings, "CALL db.awaitIndexes(30)")
    before = _graph_shape(neo4j_settings)

    hits = await _reader(env, world).search(
        CatalogResourceQueryContract(
            space_id=await _space_id(env),
            terms=("cli",),
            runtimes=("claude-code",),
            include_unsynced=True,
        )
    )

    assert {h.name: h.cataloged for h in hits} == {"plug:cli": True, "plug:new-cli": False}
    cataloged = next(h for h in hits if h.cataloged)
    assert (cataloged.revision, cataloged.discovered_runtimes) == (1, ("claude-code",))
    assert cataloged.catalog_id is not None
    assert _graph_shape(neo4j_settings) == before


async def test_reader_is_scoped_to_its_space_and_filters_by_kind(
    env: Neo4jKnowledgeEnv, world: CatalogWorld
) -> None:
    register = RegisterCatalogEntryHandler(**_deps(env))
    for index, (space, kind, name) in enumerate(
        [
            (DEFAULT_SPACE_KEY, CatalogEntryKindEnum.SKILL, "mine-quokka"),
            (OTHER_SPACE, CatalogEntryKindEnum.SKILL, "theirs-quokka"),
            (DEFAULT_SPACE_KEY, CatalogEntryKindEnum.CLI_TOOL, "quokka"),
        ]
    ):
        await register.handle(
            RegisterCatalogEntryCommand(
                idempotency_key=f"k{index}",
                space_key=space,
                kind=kind,
                name=name,
                purpose="Counts quokka sightings",
                location="https://example.invalid/q",
                actor=AGENT,
                sources=(
                    NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/q"),
                ),
            )
        )
    reader = _reader(env, world)
    mine = await _space_id(env)

    everything = await reader.search(CatalogResourceQueryContract(space_id=mine, terms=("quokka",)))
    only_tools = await reader.search(
        CatalogResourceQueryContract(space_id=mine, terms=("quokka",), kinds=("cli_tool",))
    )
    theirs = await reader.search(
        CatalogResourceQueryContract(space_id=await _space_id(env, OTHER_SPACE), terms=("quokka",))
    )

    assert sorted(h.name for h in everything) == ["mine-quokka", "quokka"]
    assert [h.name for h in only_tools] == ["quokka"]
    assert [h.name for h in theirs] == ["theirs-quokka"]
    assert all(h.cataloged and 0 < h.score <= 1 for h in everything)
    assert max(h.score for h in everything) == 1.0


async def test_search_text_with_lucene_operators_is_treated_as_plain_terms(
    env: Neo4jKnowledgeEnv, world: CatalogWorld
) -> None:
    hits = await _reader(env, world).search(
        CatalogResourceQueryContract(space_id=await _space_id(env), text='AND (x) "y" * OR :')
    )

    assert hits == []


async def test_nodes_written_before_the_discovery_fields_get_defaults_and_become_searchable(
    neo4j_settings: Neo4jConnectionSettings, world: CatalogWorld
) -> None:
    old: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(CATALOG_SCHEMA_STEP,))
    try:
        await old.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
        await RegisterCatalogEntryHandler(**_deps(old)).handle(
            RegisterCatalogEntryCommand(
                idempotency_key="legacy",
                space_key=DEFAULT_SPACE_KEY,
                kind=CatalogEntryKindEnum.CLI_TOOL,
                name="legacy-tool",
                purpose="Predates discovery",
                location="https://example.invalid/legacy",
                actor=AGENT,
                sources=(
                    NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/l"),
                ),
            )
        )
    finally:
        await old.client.close()
    query(
        neo4j_settings,
        "MATCH (r:CatalogRevision) REMOVE r:CatalogRevision "
        "REMOVE r.name, r.capabilities, r.capabilities_text, r.origin, r.manifest_digest",
    )
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=STEPS)
    try:
        assert await env.persistence.schema.apply_step("catalog_discovery")
        assert await env.persistence.schema.apply_step("catalog_fulltext")
        query(neo4j_settings, "CALL db.awaitIndexes(30)")
        space_id: SpaceId | None = await env.persistence.read_repository.get_space_id(
            DEFAULT_SPACE_KEY
        )
        assert space_id is not None

        entries = await env.persistence.catalog_read_repository.find(space_id)
        hits = await _reader(env, world).search(
            CatalogResourceQueryContract(space_id=space_id.value, terms=("predates",))
        )
    finally:
        await env.client.close()

    assert [(e.name, e.origin, e.capabilities, e.manifest_digest) for e in entries] == [
        ("legacy-tool", CatalogOriginEnum.REGISTERED, (), None)
    ]
    assert [(h.name, h.origin, h.capabilities) for h in hits] == [("legacy-tool", "registered", ())]


async def test_reader_names_the_missing_fulltext_step(
    neo4j_settings: Neo4jConnectionSettings, world: CatalogWorld
) -> None:
    bare: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=STEPS)
    try:
        await bare.persistence.schema.apply_step("core")

        with pytest.raises(StoreNotInitialisedError) as error:
            await _reader(bare, world).search(CatalogResourceQueryContract(space_id="s", text="x"))
    finally:
        await bare.client.close()

    assert error.value.metadata["missing_steps"] == ["catalog_fulltext"]
