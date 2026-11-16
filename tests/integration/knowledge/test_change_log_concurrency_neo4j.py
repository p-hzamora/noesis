"""The change counter stays unique under racing first appends, without the `change_feed` step."""

import asyncio

import pytest
from tests.support.knowledge_commands import experience_command
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env, query

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.application.services.schema_steps import CHANGE_FEED_STEP
from noesis.bounded_context.knowledge.domain.value_objects import SourceKindEnum
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

WRITERS: int = 10


async def test_racing_first_captures_create_one_counter_and_distinct_sequences(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    assert CHANGE_FEED_STEP not in await env.persistence.schema.applied_steps()
    writers: list[Neo4jKnowledgeEnv] = [make_neo4j_env(neo4j_settings) for _ in range(WRITERS)]
    try:
        results: list[CaptureResultDto] = await asyncio.gather(
            *(
                writer.capture_experience.handle(
                    experience_command(
                        f"race-{index}",
                        sources=(
                            NewSourceInput(kind=SourceKindEnum.COMMIT, locator=f"{index:040x}"),
                        ),
                    )
                )
                for index, writer in enumerate(writers)
            )
        )
    finally:
        for writer in writers:
            await writer.client.close()

    assert len(results) == WRITERS
    assert query(neo4j_settings, "MATCH (c:ChangeCounter) RETURN count(c) AS total") == [
        {"total": 1}
    ]
    rows = query(neo4j_settings, "MATCH (c:Change) RETURN c.sequence AS sequence")
    assert sorted(row["sequence"] for row in rows) == list(range(1, WRITERS + 1))
