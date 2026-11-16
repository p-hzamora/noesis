"""A cursor that meets a missing change must stop: `RETRIEVAL_202` (rebuild next)."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.retrieval.probe_projection import Neo4jProbeProjection
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge, space_id_of

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexCommand,
    SyncIndexHandler,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.exceptions import IndexRebuildRequiredError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_sync_over_a_deleted_change_raises_rebuild_required(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: str = await space_id_of(env)
    client = env.client
    cursors = Neo4jIndexCursorStoreAdapter(client, env.clock)
    handler = SyncIndexHandler(
        writers=(Neo4jProbeProjection(client),),
        cursors=cursors,
        feed=Neo4jRecordChangeFeedAdapter(client),
        states=Neo4jRecordStateReaderAdapter(client),
        indexables=Neo4jIndexableRecordReaderAdapter(client),
    )
    query(
        neo4j_settings,
        "CREATE (:IndexCursor {cursor_key: $key, projection: 'probe', space_id: $space_id, "
        "sequence: 0})",
        key=f"probe:{space_id}",
        space_id=space_id,
    )
    await capture_knowledge(env, "k1", "first")
    await capture_knowledge(env, "k2", "second")
    command = SyncIndexCommand(space_id=space_id, wait_seconds=0, owner="test")
    synced = await handler.handle(command)
    assert await cursors.get("probe", space_id) == 2
    assert synced.head_sequence == 2

    await capture_knowledge(env, "k3", "third")  # sequence 3
    query(
        neo4j_settings,
        "MATCH (c:Change {change_key: $key}) DELETE c",
        key=f"{space_id}:3",
    )
    await capture_knowledge(env, "k4", "fourth")  # sequence 4

    with pytest.raises(IndexRebuildRequiredError) as raised:
        await handler.handle(command)

    assert raised.value.error_code == "RETRIEVAL_202_INDEX_REBUILD_REQUIRED"
    assert await cursors.get("probe", space_id) == 2
