"""Facets match whole words only; the policy holds no vocabulary."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.facet_match_policy import FacetMatchPolicy

pytestmark = pytest.mark.unit
policy = FacetMatchPolicy()


@pytest.mark.parametrize(
    ("facets", "texts", "expected"),
    [
        (["cli"], ["python-suite:ddd-interface-cli"], {"cli"}),
        (["python-ddd"], ["python-suite:ddd-hexagonal-python"], {"python-ddd"}),
        (["uv"], ["uvicorn runner", "a UVLOOP thing"], set()),
        (["uv"], ["Runs UV for you"], {"uv"}),
        (["cli", "uv"], ["a cli", None, ""], {"cli"}),
        ([""], ["anything"], set()),
        (["a b"], ["b and a"], {"a b"}),
    ],
)
def test_matches_whole_words_only(
    facets: list[str], texts: list[str | None], expected: set[str]
) -> None:
    assert policy.matched(facets, *texts) == frozenset(expected)
