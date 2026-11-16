"""C5b in the search pipeline: build manifest gating (AC-207/208) and identifier fusion (AC-211)."""

import pytest
from tests.support.retrieval.retrieval_fakes import SPACE, RetrievalWorld, make_request

from noesis.bounded_context.retrieval.domain.enums import BuildStateEnum, SemanticStateEnum
from noesis.bounded_context.retrieval.domain.value_objects.projection_key import ProjectionKey
from noesis.exceptions import IndexRebuildRequiredError

pytestmark = pytest.mark.unit

PROFILE: dict[str, object] = {"name": "fake-semantic", "version": 1}


def world_with(
    *, lexical: list[str], semantic: list[str], text: str | None = None
) -> RetrievalWorld:
    world = RetrievalWorld()
    for record_id in {*lexical, *semantic}:
        world.add_knowledge(record_id)
    world.feed.add(SPACE, lexical[0] if lexical else semantic[0])
    world.cursors.set("semantic", SPACE, 1)
    world.match(*lexical, text=text)
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id=r, revision=1) for r in semantic])
    return world


async def test_a_space_being_rebuilt_is_unavailable_but_lexical_still_answers() -> None:
    world = world_with(lexical=["L"], semantic=["S"])
    world.cursors.set_manifest("semantic", SPACE, BuildStateEnum.REBUILDING)

    result = await world.searcher(with_semantic=True).search(make_request())

    assert result.semantic_state is SemanticStateEnum.UNAVAILABLE
    assert [hit.record_id for hit in result.hits] == ["L"]
    assert world.semantic.calls == []


async def test_a_built_profile_other_than_the_configured_one_requires_a_rebuild() -> None:
    world = world_with(lexical=["L"], semantic=["S"])
    world.cursors.set_manifest(
        "semantic", SPACE, BuildStateEnum.COMPLETE, {"name": "fake-semantic", "version": 2}
    )

    with pytest.raises(IndexRebuildRequiredError, match="different profile"):
        await world.searcher(with_semantic=True).search(make_request())


async def test_a_matching_built_profile_is_ready() -> None:
    world = world_with(lexical=["L"], semantic=["S"])
    world.cursors.set_manifest("semantic", SPACE, BuildStateEnum.COMPLETE, dict(PROFILE))  # type: ignore[arg-type]

    result = await world.searcher(with_semantic=True).search(make_request())

    assert result.semantic_state is SemanticStateEnum.READY
    assert {hit.record_id for hit in result.hits} == {"L", "S"}


async def test_an_ordinary_query_lets_semantic_agreement_reorder_by_rrf() -> None:
    world = world_with(lexical=["A", "B", "C"], semantic=["C", "B"])

    result = await world.searcher(with_semantic=True).search(make_request("how do leases work"))

    assert [hit.record_id for hit in result.hits][:3] == ["C", "B", "A"]  # A loses first place


async def test_an_identifier_query_keeps_the_lexical_order_and_appends_semantic_only() -> None:
    world = world_with(lexical=["A", "B", "C"], semantic=["C", "X", "B"])

    result = await world.searcher(with_semantic=True).search(
        make_request("`RecordSearcher` leases")
    )

    assert [hit.record_id for hit in result.hits] == ["A", "B", "C", "X"]
    by_id = {hit.record_id: hit for hit in result.hits}
    assert [kind.value for kind in by_id["C"].sources] == ["lexical", "semantic"]
    assert [kind.value for kind in by_id["X"].sources] == ["semantic"]


async def test_an_identifier_query_seeds_the_graph_from_lexical_only() -> None:
    world = world_with(lexical=["A"], semantic=["S"])
    world.add_knowledge("N")
    world.neighbours.add(SPACE, "N", seed_id="S")  # only reachable from the semantic seed

    identifier = await world.searcher(with_semantic=True).search(make_request("snake_case_name"))
    ordinary = await world.searcher(with_semantic=True).search(make_request("plain words"))

    assert "N" not in [hit.record_id for hit in identifier.hits]
    assert "N" in [hit.record_id for hit in ordinary.hits]


async def test_an_identifier_query_tiers_the_baseline_then_the_semantic_only_records() -> None:
    """F-5 tuning: an accepted semantic-only record never displaces a proposed exact match."""
    world = RetrievalWorld()
    world.add_knowledge("P", status="proposed")
    world.add_knowledge("Q", status="accepted")
    world.add_knowledge("X", status="accepted")
    world.feed.add(SPACE, "P")
    world.cursors.set("semantic", SPACE, 1)
    world.match("P", "Q")
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id="X", revision=1)])

    result = await world.searcher(with_semantic=True).search(make_request("NOE-12"))

    assert [hit.record_id for hit in result.hits] == ["Q", "P", "X"]


async def test_an_ordinary_query_tiers_the_whole_fused_list() -> None:
    world = RetrievalWorld()
    world.add_knowledge("P", status="proposed")
    world.add_knowledge("X", status="accepted")
    world.feed.add(SPACE, "P")
    world.cursors.set("semantic", SPACE, 1)
    world.match("P")
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id="X", revision=1)])

    result = await world.searcher(with_semantic=True).search(make_request("plain words"))

    assert [hit.record_id for hit in result.hits] == ["X", "P"]
