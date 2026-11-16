"""Catalog writes append to C5a's change feed in their own transaction (C6 AC-013), over the pinned Neo4j."""

from collections.abc import AsyncIterator

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY

from noesis.bounded_context.knowledge.application.dtos import CatalogWriteResultDto
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
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    SourceKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CATALOG_SCHEMA_STEP,
)
from noesis.exceptions import RevisionConflictError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

Entry = tuple[str, str, int | None, str | None]


@pytest.fixture
async def catalog_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Real handlers over a store after `store init` with steps `core` and `catalog`."""
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(CATALOG_SCHEMA_STEP,))
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    yield env
    await env.client.close()


def _register(key: str) -> RegisterCatalogEntryCommand:
    return RegisterCatalogEntryCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        kind=CatalogEntryKindEnum.CLI_TOOL,
        name="gh",
        purpose="GitHub CLI",
        location="https://github.com/cli/cli",
        actor=AGENT,
        sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/gh"),),
    )


def _revise(key: str, purpose: str) -> ReviseCatalogEntryCommand:
    return ReviseCatalogEntryCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        ref="cli_tool:gh",
        expected_revision=1,
        purpose=purpose,
        version=None,
        prerequisites=None,
        location=None,
        actor=AGENT,
        sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/gh"),),
    )


async def _entries_for(env: Neo4jKnowledgeEnv, space_id: str, record_id: str) -> list[Entry]:
    """Feed entries of one record, in sequence order, read through C5a's change-feed reader."""
    changes = await Neo4jRecordChangeFeedAdapter(env.client).changes_after(
        0, space_id=space_id, limit=1000
    )
    return [
        (c.change_kind, c.record_type, c.revision, c.status)
        for c in changes
        if c.record_id == record_id
    ]


async def test_ac013_register_and_revise_append_changes(catalog_env: Neo4jKnowledgeEnv) -> None:
    handlers = {
        "uow_factory": catalog_env.persistence.uow_factory,
        "clock": catalog_env.clock,
        "ids": catalog_env.persistence.ids,
        "schema": catalog_env.persistence.schema,
    }
    register = RegisterCatalogEntryHandler(**handlers)
    revise = ReviseCatalogEntryHandler(**handlers)

    registered: CatalogWriteResultDto = await register.handle(_register("k1"))
    await revise.handle(_revise("k2", "GitHub CLI, used for pull requests"))

    expected: list[Entry] = [
        ("created", "catalog_entry", 1, None),
        ("revised", "catalog_entry", 2, None),
    ]
    assert await _entries_for(catalog_env, registered.space_id, registered.id) == expected

    replay: CatalogWriteResultDto = await register.handle(_register("k1"))
    assert replay.replayed is True
    with pytest.raises(RevisionConflictError):
        await revise.handle(_revise("k3", "stale"))
    unchanged = _revise("k4", "GitHub CLI, used for pull requests").model_copy(
        update={"expected_revision": 2}
    )
    no_op: CatalogWriteResultDto = await revise.handle(unchanged)
    assert no_op.revision == 2

    assert await _entries_for(catalog_env, registered.space_id, registered.id) == expected
