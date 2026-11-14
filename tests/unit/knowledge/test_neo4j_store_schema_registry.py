"""Schema step registry: a name registered twice is rejected at start-up (A-3)."""

import pytest
from pydantic import SecretStr

from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CORE_SCHEMA_STEP,
    Neo4jSchemaStep,
    Neo4jStoreSchemaAdapter,
)
from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

pytestmark = pytest.mark.unit


def _client() -> Neo4jClient:
    return Neo4jClient(
        Neo4jConnectionSettings(uri="bolt://127.0.0.1:1", user="neo4j", password=SecretStr("x"))
    )


def test_registering_the_same_step_name_twice_is_a_configuration_error() -> None:
    duplicate = Neo4jSchemaStep(name="core", statements=())

    with pytest.raises(InvalidConfigurationError) as raised:
        Neo4jStoreSchemaAdapter(_client(), (CORE_SCHEMA_STEP, duplicate))

    assert raised.value.metadata["duplicate_steps"] == ["core"]


def test_steps_are_listed_in_registration_order_with_core_constraints_only() -> None:
    extra = Neo4jSchemaStep(name="c6_catalog", statements=())

    schema = Neo4jStoreSchemaAdapter(_client(), (CORE_SCHEMA_STEP, extra))

    assert schema.registered_steps() == ("core", "c6_catalog")
    assert len(CORE_SCHEMA_STEP.statements) == 7
    assert not any("CatalogEntry" in statement for statement in CORE_SCHEMA_STEP.statements)


async def test_applying_an_unregistered_step_is_a_configuration_error() -> None:
    schema = Neo4jStoreSchemaAdapter(_client(), (CORE_SCHEMA_STEP,))

    with pytest.raises(InvalidConfigurationError):
        await schema.apply_step("nope")
