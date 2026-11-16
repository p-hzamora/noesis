"""C5b over the pinned Neo4j 5.26 Community container, with a bag-of-words fake embedder.

AC-202 (chunk identity, null Experience revision, replacement, space isolation), AC-206 (fenced
writes and leases), AC-208 (manifest and inconsistent chunk sets), AC-209 (vector index), AC-210
(post-filter over-fetch), AC-213 (store failures propagate). No model is downloaded or run.
"""

from typing import Any

import pytest
from pydantic import SecretStr
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.retrieval.fake_embedding import FakeTextEmbedder
from tests.support.retrieval.retrieval_neo4j_support import (
    OTHER_SPACE_KEY,
    add_space,
    build_searcher,
    capture_experience,
    capture_knowledge,
    revise_knowledge,
    search_request,
    space_id_of,
)

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.retrieval.application.handlers.commands.rebuild_index_handler import (
    RebuildIndexCommand,
    RebuildIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexCommand,
    SyncIndexHandler,
)
from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    ProjectionEntryDto,
)
from noesis.bounded_context.retrieval.domain.enums import BuildStateEnum, SemanticStateEnum
from noesis.bounded_context.retrieval.domain.value_objects import ProjectionKey
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic import (
    SEMANTIC_KIND,
    Neo4jSemanticCandidateSource,
    Neo4jSemanticProjectionAdapter,
    Neo4jVectorIndexInspector,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic.neo4j_semantic_projection_adapter import (
    INCONSISTENT_REVISION,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic.neo4j_vector_index_inspector import (
    check_semantic_vector_index,
)
from noesis.exceptions import (
    GraphStoreUnavailableError,
    IndexSyncInProgressError,
    InvalidConfigurationError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    Neo4jClient,
    Neo4jConnectionSettings,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

OWNER: str = "rebuilder"


class Semantic:
    """The semantic writer, source and handlers over one env."""

    def __init__(self, env: Neo4jKnowledgeEnv, embedder: FakeTextEmbedder | None = None) -> None:
        self.env = env
        self.embedder = embedder or FakeTextEmbedder()
        self.cursors = Neo4jIndexCursorStoreAdapter(env.client, env.clock)
        self.writer = Neo4jSemanticProjectionAdapter(env.client, self.embedder, self.cursors)
        self.inspector = Neo4jVectorIndexInspector(env.client)
        self.source = Neo4jSemanticCandidateSource(env.client, self.embedder, self.inspector)
        client = env.client
        self.feed = Neo4jRecordChangeFeedAdapter(client)
        self.states = Neo4jRecordStateReaderAdapter(client)
        self.indexables = Neo4jIndexableRecordReaderAdapter(client)

    async def rebuild(self, space_id: str) -> None:
        await RebuildIndexHandler(
            writers=(self.writer,),
            cursors=self.cursors,
            feed=self.feed,
            states=self.states,
            indexables=self.indexables,
        ).handle(RebuildIndexCommand(space_id=space_id, owner=OWNER))

    async def sync(self, space_id: str) -> None:
        await SyncIndexHandler(
            writers=(self.writer,),
            cursors=self.cursors,
            feed=self.feed,
            states=self.states,
            indexables=self.indexables,
        ).handle(SyncIndexCommand(space_id=space_id, owner=OWNER))


def embeddings(settings: Neo4jConnectionSettings, record_id: str) -> list[dict[str, Any]]:
    return query(
        settings,
        "MATCH (e:Embedding {record_id: $id}) RETURN e.embedding_key AS key, e.revision AS "
        "revision, e.revision_key AS revision_key, e.chunk_index AS chunk, e.space_id AS space "
        "ORDER BY chunk",
        id=record_id,
    )


async def test_the_vector_index_is_online_with_384_cosine_and_the_check_passes(
    env: Neo4jKnowledgeEnv,
) -> None:
    inspector = Neo4jVectorIndexInspector(env.client)

    found = await inspector.wait_online()

    assert found.queryable
    assert (found.dimensions, found.similarity) == (384, "COSINE")
    await check_semantic_vector_index(env.client)


async def test_an_incompatible_vector_index_is_reported_never_dropped(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    query(neo4j_settings, "DROP INDEX retrieval_semantic_vector")
    query(
        neo4j_settings,
        "CREATE VECTOR INDEX retrieval_semantic_vector FOR (e:Embedding) ON (e.vector) "
        "OPTIONS {indexConfig: {`vector.dimensions`: 8, `vector.similarity_function`: 'euclidean'}}",
    )
    semantic = Semantic(env)

    with pytest.raises(InvalidConfigurationError, match="incompatible"):
        await check_semantic_vector_index(env.client)
    with pytest.raises(CandidateSourceUnavailableError, match="incompatible"):
        await semantic.source.find("x", space_id=await space_id_of(env), limit=5)
    assert query(neo4j_settings, "SHOW VECTOR INDEXES YIELD name RETURN name")


async def test_a_missing_vector_index_makes_semantic_unavailable_not_the_search(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    await capture_knowledge(env, "k1", "lease renewal", body="lease renewal heartbeat")
    semantic = Semantic(env)
    await semantic.rebuild(space_id)
    query(neo4j_settings, "DROP INDEX retrieval_semantic_vector")

    with pytest.raises(InvalidConfigurationError, match="missing"):
        await check_semantic_vector_index(env.client)
    result = await build_searcher(env, candidate_sources=(semantic.source,)).search(
        search_request("lease", space_id)
    )

    assert result.semantic_state is SemanticStateEnum.UNAVAILABLE
    assert len(result.hits) == 1


async def test_knowledge_and_experience_chunks_have_unique_keys_and_a_null_experience_revision(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    knowledge = await capture_knowledge(env, "k1", "Lease renewal", body="heartbeat " * 900)
    experience = await capture_experience(env, "e1", "the sync stalled on a lease")
    semantic = Semantic(env)

    await semantic.rebuild(space_id)

    knowledge_rows = embeddings(neo4j_settings, knowledge)
    experience_rows = embeddings(neo4j_settings, experience)
    assert len(knowledge_rows) == 3  # 902 tokens: windows 0-448, 384-832, 768-902
    assert {row["revision"] for row in knowledge_rows} == {1}
    assert experience_rows[0]["revision"] is None
    assert experience_rows[0]["revision_key"] == "none"
    keys = [row["key"] for row in knowledge_rows + experience_rows]
    assert len(set(keys)) == len(keys)
    assert await semantic.writer.entries(space_id) == {knowledge: 1, experience: None}
    manifest = await semantic.cursors.manifest(SEMANTIC_KIND, space_id)
    assert manifest is not None
    assert manifest.state is BuildStateEnum.COMPLETE
    assert manifest.profile == semantic.writer.profile()


async def test_find_returns_one_key_per_record_best_chunk_first_with_null_experience_revision(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    long_one = await capture_knowledge(env, "k1", "Indexing", body="lease heartbeat renewal " * 400)
    experience = await capture_experience(env, "e1", "lease heartbeat renewal fencing")
    await capture_knowledge(env, "k2", "Unrelated", body="cooking pasta recipes")
    semantic = Semantic(env)
    await semantic.rebuild(space_id)

    found = await semantic.source.find(
        "lease heartbeat renewal fencing", space_id=space_id, limit=10
    )

    assert found.hits[0] == ProjectionKey(record_id=experience, revision=None)
    ids = [key.record_id for key in found.hits]
    assert ids.count(long_one) == 1
    assert semantic.source.last_attempts[0] == 40


async def test_spaces_never_leak_or_delete_each_other(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    other_id = await add_space(env)
    mine = await capture_knowledge(env, "k1", "lease", body="lease renewal")
    theirs = await capture_knowledge(
        env, "k1", "lease", body="lease renewal", space_key=OTHER_SPACE_KEY
    )
    semantic = Semantic(env)
    await semantic.rebuild(space_id)
    await semantic.rebuild(other_id)

    await semantic.rebuild(space_id)  # clears and refills only this space
    found = await semantic.source.find("lease renewal", space_id=space_id, limit=10)

    assert [key.record_id for key in found.hits] == [mine]
    assert embeddings(neo4j_settings, theirs)[0]["space"] == other_id


async def test_a_shortened_revision_replaces_every_old_chunk_on_sync(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    record = await capture_knowledge(env, "k1", "Long", body="word " * 1_000)
    semantic = Semantic(env)
    await semantic.rebuild(space_id)
    assert len(embeddings(neo4j_settings, record)) == 3

    await revise_knowledge(env, record, "k1-r2", expected=1, body="now short")
    await semantic.sync(space_id)

    rows = embeddings(neo4j_settings, record)
    assert [(row["revision"], row["chunk"]) for row in rows] == [(2, 0)]


async def test_an_unchanged_record_is_not_re_embedded(env: Neo4jKnowledgeEnv) -> None:
    space_id = await space_id_of(env)
    await capture_knowledge(env, "k1", "Lease", body="lease renewal")
    semantic = Semantic(env)
    await semantic.rebuild(space_id)
    embedded = len(semantic.embedder.engine.passages)

    await semantic.rebuild(space_id)  # cleared, so embedded again
    assert len(semantic.embedder.engine.passages) == embedded + 1

    record = (await semantic.states.scan_states(space_id, after_id=None, limit=10))[0]
    entry = ProjectionEntryDto(
        key=ProjectionKey(record_id=record.record_id, revision=record.head_revision),
        space_id=space_id,
        record=await semantic.indexables.get(record.record_id, 1, space_id=space_id),
    )
    prepared = await semantic.writer.prepare(entry)
    assert prepared.unchanged
    assert len(semantic.embedder.engine.passages) == embedded + 1


async def test_a_commit_without_the_live_lease_writes_nothing(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    record = await capture_knowledge(env, "k1", "Lease", body="lease renewal")
    semantic = Semantic(env)
    entry = ProjectionEntryDto(
        key=ProjectionKey(record_id=record, revision=1),
        space_id=space_id,
        record=await semantic.indexables.get(record, 1, space_id=space_id),
    )
    prepared = await semantic.writer.prepare(entry)
    assert await semantic.cursors.acquire(SEMANTIC_KIND, space_id, "worker-a", 1)
    env.clock.advance(2)
    assert await semantic.cursors.acquire(SEMANTIC_KIND, space_id, "worker-b", 300)
    await semantic.cursors.release(SEMANTIC_KIND, space_id, "worker-b")

    with pytest.raises(IndexSyncInProgressError):
        await semantic.writer.commit(prepared, owner="worker-a")
    with pytest.raises(IndexSyncInProgressError):
        await semantic.writer.clear_fenced(space_id, owner="worker-a")
    with pytest.raises(IndexSyncInProgressError):
        await semantic.cursors.advance(SEMANTIC_KIND, space_id, 5, owner="worker-a")
    with pytest.raises(IndexSyncInProgressError):
        await semantic.cursors.complete_rebuild(
            SEMANTIC_KIND, space_id, owner="worker-a", profile={}
        )
    assert not await semantic.cursors.renew(SEMANTIC_KIND, space_id, "worker-a", 300)
    assert embeddings(neo4j_settings, record) == []
    assert await semantic.cursors.get(SEMANTIC_KIND, space_id) is None


async def test_renewal_extends_a_live_lease(env: Neo4jKnowledgeEnv) -> None:
    space_id = await space_id_of(env)
    cursors = Neo4jIndexCursorStoreAdapter(env.client, env.clock)
    assert await cursors.acquire(SEMANTIC_KIND, space_id, "worker-a", 2)
    env.clock.advance(1)

    assert await cursors.renew(SEMANTIC_KIND, space_id, "worker-a", 2)
    env.clock.advance(1)  # t+2: past the first expiry, inside the renewed one (t+3)
    assert not await cursors.acquire(SEMANTIC_KIND, space_id, "worker-b", 2)
    env.clock.advance(2)
    assert await cursors.acquire(SEMANTIC_KIND, space_id, "worker-b", 2)


async def test_a_pre_manifest_cursor_reads_complete_and_none_reads_absent(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    cursors = Neo4jIndexCursorStoreAdapter(env.client, env.clock)

    assert await cursors.manifest("probe", space_id) is None
    assert await cursors.acquire("probe", space_id, "x", 300)
    assert await cursors.manifest("probe", space_id) is None  # a lock alone is no build
    await cursors.advance("probe", space_id, 3)
    manifest = await cursors.manifest("probe", space_id)
    assert manifest is not None
    assert manifest.state is BuildStateEnum.COMPLETE
    assert manifest.profile is None


async def test_an_inconsistent_chunk_set_is_reported_for_verify(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = await space_id_of(env)
    record = await capture_knowledge(env, "k1", "Long", body="word " * 1_000)
    semantic = Semantic(env)
    await semantic.rebuild(space_id)

    query(
        neo4j_settings,
        "MATCH (e:Embedding {record_id: $id, chunk_index: 1}) DETACH DELETE e",
        id=record,
    )

    assert await semantic.writer.entries(space_id) == {record: INCONSISTENT_REVISION}


async def test_search_with_the_semantic_source_adds_semantic_provenance(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    meaning = await capture_experience(env, "e1", "heartbeat fencing stale writer")
    await capture_knowledge(env, "k1", "Pasta", body="cooking")
    semantic = Semantic(env)
    await semantic.rebuild(space_id)

    result = await build_searcher(env, candidate_sources=(semantic.source,)).search(
        search_request("fencing heartbeat", space_id)
    )

    assert result.semantic_state is SemanticStateEnum.READY
    by_id = {hit.record_id: hit for hit in result.hits}
    assert "semantic" in [kind.value for kind in by_id[meaning].sources]
    assert by_id[meaning].revision is None


async def test_a_sparse_space_gets_k_doubled_until_the_chunk_total(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    other_id = await add_space(env)
    for index in range(30):
        await capture_knowledge(
            env, f"o{index}", "lease", body="lease renewal heartbeat", space_key=OTHER_SPACE_KEY
        )
    mine = await capture_knowledge(env, "k1", "Pasta", body="pasta")
    semantic = Semantic(env)
    await semantic.rebuild(space_id)
    await semantic.rebuild(other_id)

    found = await semantic.source.find("lease renewal heartbeat", space_id=space_id, limit=1)

    assert [key.record_id for key in found.hits] == [mine]
    assert semantic.source.last_attempts == [4, 8, 16, 31]


async def test_a_store_outage_propagates_as_a_typed_store_error(env: Neo4jKnowledgeEnv) -> None:
    dead = Neo4jClient(
        Neo4jConnectionSettings(
            uri="bolt://127.0.0.1:1",
            user="neo4j",
            password=SecretStr("x"),
            connect_timeout_seconds=1,
        )
    )
    source = Neo4jSemanticCandidateSource(dead, FakeTextEmbedder(), Neo4jVectorIndexInspector(dead))
    try:
        with pytest.raises(GraphStoreUnavailableError):
            await source.find("x", space_id="s", limit=1)
    finally:
        await dead.close()


async def test_an_over_long_query_is_semantic_unavailable(env: Neo4jKnowledgeEnv) -> None:
    semantic = Semantic(env)

    with pytest.raises(CandidateSourceUnavailableError, match="32000"):
        await semantic.source.find("x" * 32_001, space_id="s", limit=1)
