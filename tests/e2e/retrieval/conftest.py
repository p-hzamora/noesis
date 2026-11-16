"""Retrieval e2e: an in-process seeding environment and the matching child environment."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import store_environment
from tests.support.retrieval.retrieval_neo4j_support import initialised_env
from tests.support.retrieval.retrieval_process_support import ACTIVE_SPACE

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings


@pytest.fixture
async def env(neo4j_settings: Neo4jConnectionSettings) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Seeding handlers over a database after `store init` (all C5a steps, space `default`)."""
    async for ready in initialised_env(neo4j_settings):
        yield ready


@pytest.fixture
def child_env(tmp_path: Path, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child process environment for the container, active space `default`."""
    return store_environment(tmp_path / "child-home", ACTIVE_SPACE, neo4j_settings)


@pytest.fixture
async def core_only_env(
    neo4j_settings: Neo4jConnectionSettings,
) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Seeding handlers over a database initialised with C2's `core` step only."""
    async for ready in initialised_env(neo4j_settings, with_retrieval_steps=False):
        yield ready
