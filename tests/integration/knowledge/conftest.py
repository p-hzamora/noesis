"""Knowledge over the pinned Neo4j container: a ready environment per test."""

from collections.abc import AsyncIterator
from typing import Any

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


@pytest.fixture
async def review_bare_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Any]:
    """C4's handlers over an empty database whose schema registry holds `core` and `review`."""
    from tests.support.review_support import make_review_neo4j_env  # C4 modules: imported lazily

    review_env = make_review_neo4j_env(neo4j_settings)
    yield review_env
    await review_env.client.close()


@pytest.fixture
async def review_env(review_bare_env: Any) -> Any:
    """`review_bare_env` after `store init` (both steps applied, default space `default`)."""
    await review_bare_env.initialise()
    return review_bare_env


@pytest.fixture
async def consolidation_bare_env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Any]:
    """C9's handlers over an empty database whose registry holds `core`, `review`, `consolidation`."""
    from tests.support.consolidation_support import make_consolidation_env

    env = make_consolidation_env(neo4j_settings)
    yield env
    await env.client.close()


@pytest.fixture
async def consolidation_env(consolidation_bare_env: Any) -> Any:
    """`consolidation_bare_env` after `store init` (every registered step, default space)."""
    await consolidation_bare_env.review.initialise()
    return consolidation_bare_env
