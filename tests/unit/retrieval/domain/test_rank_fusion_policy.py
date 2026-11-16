"""Reciprocal-rank fusion keyed by record id (offset 60, stable ties)."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.rank_fusion_policy import RankFusionPolicy

pytestmark = pytest.mark.unit


def fuse(*rankings: list[str]) -> list[str]:
    return list(RankFusionPolicy().fuse(list(rankings)))


def test_a_single_ranking_keeps_its_order() -> None:
    assert fuse(["a", "b", "c"]) == ["a", "b", "c"]


def test_a_record_ranked_by_both_sources_rises_above_one_ranked_first_by_one() -> None:
    assert fuse(["a", "b", "c"], ["c", "x", "y"])[0] == "c"


def test_offset_is_60_so_agreement_beats_a_single_first_place() -> None:
    """With offset 60, `y` (position 4 twice: 2/64) beats `x` (position 0 once: 1/60); a small offset would not."""
    fused = fuse(["x", "p", "q", "r", "y"], ["s", "t", "u", "v", "y"])

    assert fused[0] == "y"


def test_ties_keep_the_order_of_first_appearance() -> None:
    # a and b both score 1/60 + 1/61 vs. 1/61 + 1/60: a tie broken by first appearance
    assert fuse(["a", "b"], ["b", "a"]) == ["a", "b"]


def test_every_record_appears_once() -> None:
    fused = fuse(["a", "b"], ["b", "c"], ["c", "a"])

    assert sorted(fused) == ["a", "b", "c"]


def test_no_rankings_fuse_to_nothing() -> None:
    assert fuse() == []
    assert fuse([], []) == []


def test_protect_keeps_the_baseline_and_appends_only_new_records() -> None:
    protected = RankFusionPolicy().protect(["a", "b", "c"], ["c", "x", "a", "y", "x"])

    assert protected == ["a", "b", "c", "x", "y"]


def test_protect_with_an_empty_baseline_is_the_extra_order() -> None:
    assert RankFusionPolicy().protect([], ["x", "y"]) == ["x", "y"]
