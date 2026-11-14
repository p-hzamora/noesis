"""Knowledge over the pinned Neo4j container: a ready environment per test."""

from collections.abc import AsyncIterator

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env
from tests.support.knowledge_support import DEFAULT_SPACE_KEY

from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings


@pytest.fixture
async def bare_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Handlers over an empty, uninitialised database."""
    env: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    yield env
    await env.client.close()


@pytest.fixture
async def env(bare_env: Neo4jKnowledgeEnv) -> Neo4jKnowledgeEnv:
    """Handlers over a database after `store init` (default space `default`)."""
    await bare_env.initialise_store.handle(
        InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
    )
    return bare_env
