"""AC-022: the related lookup returns `RecordSearchHitContract`, equal to `RecordSearcher.search`."""

from datetime import datetime

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.knowledge_support import NOW
from tests.support.retrieval.retrieval_neo4j_support import (
    build_searcher,
    capture_knowledge,
    search_request,
    space_id_of,
)
from tests.support.retrieval.status_writer import set_status

from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge.related_record_finder_adapter import (
    RelatedRecordFinderAdapter,
)
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

HIT_KEYS = {
    "record_id",
    "record_type",
    "subtype",
    "title",
    "revision",
    "status",
    "authority",
    "project_id",
    "sources",
    "revised_at",
    "rank",
}


async def test_ac022(env: Neo4jKnowledgeEnv) -> None:
    space_id: str = await space_id_of(env)
    ka = await capture_knowledge(env, "ka", "ports in acme", project="acme")
    kg = await capture_knowledge(env, "kg", "ports everywhere")
    kr = await capture_knowledge(env, "kr", "ports retracted", project="acme")
    ko = await capture_knowledge(env, "ko", "ports elsewhere", project="other")
    await set_status(
        env.client, space_id=space_id, record_id=ka, status="accepted", occurred_at=NOW
    )
    await set_status(
        env.client, space_id=space_id, record_id=kr, status="retracted", occurred_at=NOW
    )
    searcher = build_searcher(env)

    found = await RelatedRecordFinderAdapter(searcher).find(
        "ports", space_id=space_id, project_key="acme", limit=8
    )
    expected = await searcher.search(search_request("ports", space_id, project_key="acme", limit=8))

    assert isinstance(found, RecordSearchHitContract)
    assert found.contract_version == 1
    assert {hit.record_id for hit in found.hits} == {ka, kg}
    assert kr not in {hit.record_id for hit in found.hits}
    assert ko not in {hit.record_id for hit in found.hits}
    assert len(found.hits) == len(expected.hits)
    for item, dto in zip(found.hits, expected.hits, strict=True):
        assert set(item.model_dump()) == HIT_KEYS
        assert item.record_id == dto.record_id
        assert item.record_type == str(dto.record_type)
        assert item.subtype == dto.subtype
        assert item.title == dto.title
        assert item.revision == dto.revision
        assert item.status == (None if dto.status is None else str(dto.status))
        assert item.authority == str(dto.authority)
        assert item.project_id == dto.project_id
        assert list(item.sources) == [str(source) for source in dto.sources]
        assert item.rank == dto.rank
        assert datetime.fromisoformat(item.revised_at) == dto.revised_at
        assert item.revised_at.endswith("Z")
    assert found.pending_changes == expected.pending_changes == 0
    assert found.semantic_state == str(expected.semantic_state) == "absent"
    assert RecordSearchHitContract.model_validate_json(found.model_dump_json()) == found
