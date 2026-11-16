"""RelatedRecordFinderAdapter, C7's related lookup over RecordSearcher (AC-022, FR-020)."""

import pytest
from tests.support.retrieval.retrieval_fakes import SPACE, RetrievalWorld, make_request

from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge.related_record_finder_adapter import (
    RelatedRecordFinderAdapter,
)
from noesis.exceptions import IndexRebuildRequiredError
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract

pytestmark = pytest.mark.unit

ELEVEN_KEYS: set[str] = {
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


def seeded_world() -> RetrievalWorld:
    """Ka (acme, accepted), Kg (space-wide, proposed), Kr (acme, retracted), Ko (other)."""
    world = RetrievalWorld()
    world.states.add_project(SPACE, "acme", "P-acme")
    world.states.add_project(SPACE, "other", "P-other")
    world.add_knowledge("Ka", status="accepted", project_id="P-acme")
    world.add_knowledge("Kg", status="proposed")
    world.add_knowledge("Kr", status="retracted", project_id="P-acme")
    world.add_knowledge("Ko", status="accepted", project_id="P-other")
    world.match("Kg", "Ko", "Kr", "Ka")
    return world


async def test_ac022() -> None:
    world = seeded_world()
    searcher = world.searcher()

    contract = await RelatedRecordFinderAdapter(searcher=searcher).find(
        "ports", space_id=SPACE, project_key="acme", limit=8
    )

    expected = await searcher.search(make_request("ports", project_key="acme", limit=8))
    assert isinstance(contract, RecordSearchHitContract)
    assert contract.contract_version == 1
    assert [h.record_id for h in contract.hits] == ["Ka", "Kg"]  # no Kr (retracted), no Ko (other)
    assert [h.record_id for h in contract.hits] == [h.record_id for h in expected.hits]
    for item, hit in zip(contract.hits, expected.hits, strict=True):
        assert set(type(item).model_fields) == ELEVEN_KEYS
        assert item.record_type == hit.record_type
        assert item.subtype == hit.subtype
        assert item.title == hit.title
        assert item.revision == hit.revision
        assert item.status == hit.status
        assert item.authority == hit.authority.value
        assert item.project_id == hit.project_id
        assert item.sources == tuple(kind.value for kind in hit.sources)
        assert item.revised_at == "2026-01-01T00:00:00Z"
        assert item.rank == hit.rank
    assert contract.pending_changes == expected.pending_changes == 0
    assert contract.semantic_state == expected.semantic_state.value == "absent"


async def test_ac022_survives_a_json_round_trip() -> None:
    contract = await RelatedRecordFinderAdapter(searcher=seeded_world().searcher()).find(
        "ports", space_id=SPACE, project_key="acme", limit=8
    )

    assert RecordSearchHitContract.model_validate_json(contract.model_dump_json()) == contract


async def test_find_asks_for_no_stale_and_no_semantic_requirement() -> None:
    """A related lookup works with no semantic source registered (`require_semantic` is false)."""
    contract = await RelatedRecordFinderAdapter(searcher=seeded_world().searcher()).find(
        "ports", space_id=SPACE, project_key=None, limit=8
    )

    assert [h.record_id for h in contract.hits] == ["Kg"]  # no project key: space-wide only
    assert contract.semantic_state == "absent"


async def test_searcher_errors_propagate_unchanged() -> None:
    world = seeded_world()
    world.semantic.set_profile({"model": "m2"})
    searcher = world.searcher(with_semantic=True, configured_profiles={"semantic": {"model": "m1"}})

    with pytest.raises(IndexRebuildRequiredError):
        await RelatedRecordFinderAdapter(searcher=searcher).find(
            "ports", space_id=SPACE, project_key="acme", limit=8
        )
