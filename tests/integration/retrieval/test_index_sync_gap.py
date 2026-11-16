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


async def test_unknown_rows_decode_and_advance_real_cursor_without_indexing(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space = await space_id_of(env)
    record = await capture_knowledge(env, "k1", "first")
    query(
        neo4j_settings,
        "CREATE (:IndexCursor {cursor_key: $key, projection: 'probe', space_id: $space, sequence: 0})",
        key=f"probe:{space}",
        space=space,
    )
    query(
        neo4j_settings,
        """MATCH (original:Change {space_id: $space, sequence: 1})
    UNWIND range(2, 103) AS seq
    CREATE (future:Change)
    SET future = original{.*, change_key: $space + ':' + toString(seq),
        event_id: 'future-' + toString(seq), sequence: seq,
        record_id: 'unread', change_kind: 'future_kind'}
    WITH count(*) AS total
    MATCH (counter:ChangeCounter {space_id: $space}) SET counter.value = 103
    """,
        space=space,
    )
    cursors = Neo4jIndexCursorStoreAdapter(env.client, env.clock)
    writer = Neo4jProbeProjection(env.client)
    handler = SyncIndexHandler(
        writers=(writer,),
        cursors=cursors,
        feed=Neo4jRecordChangeFeedAdapter(env.client),
        states=Neo4jRecordStateReaderAdapter(env.client),
        indexables=Neo4jIndexableRecordReaderAdapter(env.client),
    )
    result = await handler.handle(SyncIndexCommand(space_id=space, wait_seconds=0, owner="test"))
    assert result.projections[0].unknown_changes == 102
    assert await cursors.get("probe", space) == 103
    assert await writer.entries(space) == {record: 1}
