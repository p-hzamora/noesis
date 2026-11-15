"""`store init` and named schema steps against the pinned Neo4j (AC-011, AC-014, AC-020, AC-021)."""

from typing import Any

import pytest
from tests.support.knowledge_neo4j_support import (
    Neo4jKnowledgeEnv,
    make_neo4j_env,
    node_counts,
    query,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY

from noesis.bounded_context.knowledge.application.dtos import StoreInitialisedDto
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.application.services.schema_steps import require_steps
from noesis.bounded_context.knowledge.domain.value_objects import (
    RecordId,
    Slug,
    SourceKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import Neo4jSchemaStep
from noesis.exceptions import StoreNotInitialisedError
from noesis.interfaces.cli.bootstrap.retrieval_handlers_builder import RETRIEVAL_SCHEMA_STEPS
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

FAKE_STEP: Neo4jSchemaStep = Neo4jSchemaStep(
    name="c9_fake",
    statements=("CREATE INDEX c9_fake_index IF NOT EXISTS FOR (n:FakeC9) ON (n.value)",),
)
ALL_STEPS: tuple[str, ...] = ("core", "review", "change_feed", "knowledge_fulltext", "retrieval_index")
CORE_CONSTRAINTS: set[tuple[str, str]] = {
    ("Record", "id"),
    ("Space", "id"),
    ("Space", "key"),
    ("Revision", "revision_key"),
    ("Project", "project_key"),
    ("Source", "source_key"),
    ("IdempotencyKey", "key"),
}


def _init() -> InitialiseStoreCommand:
    return InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)


async def test_record_get_on_an_empty_store_names_the_missing_step_and_writes_nothing(
    bare_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    with pytest.raises(StoreNotInitialisedError) as raised:
        await bare_env.get_record.handle(
            GetRecordQuery(
                space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value="01JD0000000000000000000000")
            )
        )

    assert raised.value.error_code == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert raised.value.metadata["missing_steps"] == ["core"]
    assert node_counts(neo4j_settings) == {}


async def test_store_init_twice_applies_every_registered_step_once_and_ensures_one_default_space(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    """With C5a's three steps registered after `core` (the production registry)."""
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=RETRIEVAL_SCHEMA_STEPS)
    try:
        first: StoreInitialisedDto = await env.initialise_store.handle(_init())
        second: StoreInitialisedDto = await env.initialise_store.handle(_init())
    finally:
        await env.client.close()

    assert first.applied_steps == ALL_STEPS
    assert first.default_space.created
    assert second.applied_steps == ()
    assert second.already_applied_steps == ALL_STEPS
    assert not second.default_space.created
    assert second.default_space.id == first.default_space.id
    assert query(neo4j_settings, "MATCH (s:Space) RETURN s.key AS key") == [{"key": "default"}]
    assert query(neo4j_settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps") == [
        {"steps": list(ALL_STEPS)}
    ]


async def test_store_init_creates_only_single_property_uniqueness_constraints(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    constraints: list[dict[str, Any]] = query(neo4j_settings, "SHOW CONSTRAINTS")

    assert {row["type"] for row in constraints} == {"UNIQUENESS"}
    assert all(len(row["properties"]) == 1 for row in constraints)
    assert all(len(row["labelsOrTypes"]) == 1 for row in constraints)
    assert {(row["labelsOrTypes"][0], row["properties"][0]) for row in constraints} == (
        CORE_CONSTRAINTS
    )
    assert len(constraints) == len(CORE_CONSTRAINTS)  # nothing for the reserved CatalogEntry


async def test_a_second_registered_step_is_applied_once_over_two_inits_and_recorded(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(FAKE_STEP,))
    try:
        first: StoreInitialisedDto = await env.initialise_store.handle(_init())
        second: StoreInitialisedDto = await env.initialise_store.handle(_init())
    finally:
        await env.client.close()

    assert first.applied_steps == ("core", "c9_fake")
    assert second.applied_steps == ()
    assert second.already_applied_steps == ("core", "c9_fake")
    assert query(neo4j_settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps") == [
        {"steps": ["core", "c9_fake"]}
    ]
    assert query(neo4j_settings, "SHOW INDEXES YIELD name WHERE name = 'c9_fake_index' RETURN name")


async def test_a_command_requiring_an_unapplied_step_fails_naming_it_and_writes_nothing(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings, extra_steps=(FAKE_STEP,))
    try:
        assert await env.persistence.schema.apply_step("core")
        before: dict[str, int] = node_counts(neo4j_settings)

        with pytest.raises(StoreNotInitialisedError) as raised:
            await require_steps(env.persistence.schema, "core", "c9_fake")
    finally:
        await env.client.close()

    assert raised.value.metadata["missing_steps"] == ["c9_fake"]
    assert "c9_fake" in raised.value.message
    assert node_counts(neo4j_settings) == before


async def test_capture_on_an_uninitialised_store_writes_nothing(
    bare_env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    with pytest.raises(StoreNotInitialisedError):
        await bare_env.capture_knowledge.handle(
            CaptureKnowledgeCommand(
                idempotency_key="k-1",
                space_key=DEFAULT_SPACE_KEY,
                title="T",
                body="B",
                subtype=Slug(value="decision"),
                actor=AGENT,
                sources=(NewSourceInput(kind=SourceKindEnum.COMMIT, locator="a" * 40),),
            )
        )

    assert node_counts(neo4j_settings) == {}
