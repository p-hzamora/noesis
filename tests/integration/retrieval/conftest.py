"""Retrieval over the pinned Neo4j container: handlers with the C5a schema steps applied."""

from collections.abc import AsyncIterator

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import initialised_env

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings


@pytest.fixture
async def env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Handlers over a wiped database after `store init` with `core` and the three C5a steps."""
    async for ready in initialised_env(neo4j_settings):
        yield ready


@pytest.fixture
async def core_only_env(
    neo4j_settings: Neo4jConnectionSettings,
) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Handlers over a database initialised with C2's `core` step only."""
    async for ready in initialised_env(neo4j_settings, with_retrieval_steps=False):
        yield ready
