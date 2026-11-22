"""AC-004: prerequisites first; bounded and cycle-safe."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.load_order_policy import (
    MAX_ADDED,
    MAX_DEPTH,
    LoadOrderPolicy,
)

pytestmark = pytest.mark.unit
policy = LoadOrderPolicy()


def test_prerequisite_precedes_dependent() -> None:
    result = policy.order(["B"], {"B": ["A"]})
    assert result.order == ("A", "B")
    assert result.added == ("A",)
    assert result.warnings == ()


def test_shared_prerequisite_is_emitted_once_and_roots_keep_order() -> None:
    result = policy.order(["B", "C"], {"B": ["A"], "C": ["A"]})
    assert result.order == ("A", "B", "C")


def test_selected_root_as_prerequisite_is_not_counted_as_added() -> None:
    result = policy.order(["B", "A"], {"B": ["A"]})
    assert result.order == ("A", "B")
    assert result.added == ()


def test_cycle_stops_at_revisit_with_warning() -> None:
    result = policy.order(["A"], {"A": ["B"], "B": ["A"]})
    assert result.order == ("B", "A")
    assert any("cycle" in w and "A" in w for w in result.warnings)


def test_self_cycle() -> None:
    result = policy.order(["A"], {"A": ["A"]})
    assert result.order == ("A",)
    assert result.warnings


def test_depth_is_truncated() -> None:
    chain = {f"n{i}": [f"n{i + 1}"] for i in range(10)}
    result = policy.order(["n0"], chain)
    assert result.order == tuple(f"n{i}" for i in range(MAX_DEPTH, -1, -1))
    assert any(f"n{MAX_DEPTH + 1}" in w for w in result.warnings)


def test_added_count_is_truncated() -> None:
    wide = {"R": [f"p{i}" for i in range(MAX_ADDED + 3)]}
    result = policy.order(["R"], wide)
    assert len(result.added) == MAX_ADDED
    assert result.order[-1] == "R"
    assert len([w for w in result.warnings if "limit" in w]) == 3


def test_unknown_refs_have_no_prerequisites() -> None:
    assert policy.order(["X"], {}).order == ("X",)
    assert policy.order([], {"A": ["B"]}).order == ()
