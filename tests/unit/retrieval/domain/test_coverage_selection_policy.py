"""Greedy cover: new facets, then relevance, then authority; same-kind redundancy skipped."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.coverage_selection_policy import (
    CoverageSelectionPolicy,
)
from noesis.bounded_context.retrieval.domain.value_objects.coverage_candidate import (
    CoverageCandidate,
)

pytestmark = pytest.mark.unit
policy = CoverageSelectionPolicy()


def cand(id_: str, kind: str, facets: set[str], rel: int = 0, auth: int = 0) -> CoverageCandidate:
    return CoverageCandidate(
        id=id_, kind=kind, facets=frozenset(facets), relevance_rank=rel, authority_rank=auth
    )


def ids(picked: tuple[CoverageCandidate, ...]) -> list[str]:
    return [c.id for c in picked]


def test_most_new_facets_first_then_relevance_then_authority() -> None:
    items = [
        cand("one", "skill", {"a"}, rel=0),
        cand("two", "skill", {"a", "b"}, rel=5),
        cand("tie_rel", "agent", {"c"}, rel=1, auth=9),
        cand("tie_auth", "cli", {"c"}, rel=1, auth=1),
    ]
    assert ids(policy.select(items, ["a", "b", "c"], 4))[:2] == ["two", "tie_auth"]


def test_same_kind_covering_only_covered_facets_is_skipped() -> None:
    items = [cand("x", "skill", {"a"}), cand("y", "skill", {"a"}), cand("z", "agent", {"a"})]
    assert ids(policy.select(items, ["a"], 5)) == ["x", "z"]


def test_limit_stops_selection() -> None:
    items = [cand(str(i), "skill", {f"f{i}"}, rel=i) for i in range(5)]
    assert len(policy.select(items, [f"f{i}" for i in range(5)], 2)) == 2


def test_no_facets_selects_by_relevance() -> None:
    items = [cand("b", "skill", set(), rel=2), cand("a", "skill", set(), rel=1)]
    assert ids(policy.select(items, [], 8)) == ["a", "b"]


def test_empty_candidates_and_zero_limit() -> None:
    assert policy.select([], ["a"], 3) == ()
    assert policy.select([cand("a", "skill", {"a"})], ["a"], 0) == ()


def test_resource_named_for_a_facet_is_kept_when_another_only_mentions_it() -> None:
    mentions = CoverageCandidate(
        id="broad", kind="skill", facets=frozenset({"a", "b"}), named_facets=frozenset({"b"})
    )
    named = CoverageCandidate(
        id="exact",
        kind="skill",
        facets=frozenset({"a"}),
        named_facets=frozenset({"a"}),
        relevance_rank=3,
    )
    assert ids(policy.select([mentions, named], ["a", "b"], 5)) == ["broad", "exact"]
