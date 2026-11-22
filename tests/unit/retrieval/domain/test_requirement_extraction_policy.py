"""Facets come from explicit needs, else salient terms; no vocabulary."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import RequirementSourceEnum
from noesis.bounded_context.retrieval.domain.policies.requirement_extraction_policy import (
    MAX_QUERY_TERMS,
    RequirementExtractionPolicy,
)

pytestmark = pytest.mark.unit
policy = RequirementExtractionPolicy()


def test_needs_win_over_query_and_are_deduplicated() -> None:
    facets = policy.extract("anything at all", (" uv ", "UV", "python-ddd", ""))
    assert [(f.id, f.source) for f in facets] == [
        ("uv", RequirementSourceEnum.NEED),
        ("python-ddd", RequirementSourceEnum.NEED),
    ]


def test_query_terms_drop_grammar_words_and_keep_identifiers() -> None:
    facets = policy.extract("how do I add the RecordSearcher to src/noesis/x.py?")
    assert [f.id for f in facets] == ["add", "recordsearcher", "src/noesis/x.py"]
    assert {f.source for f in facets} == {RequirementSourceEnum.QUERY}


def test_only_grammar_words_yield_no_facets() -> None:
    assert policy.extract("what is the of a") == ()


def test_query_terms_are_bounded() -> None:
    query = " ".join(f"word{i}x" for i in range(30))
    assert len(policy.extract(query)) == MAX_QUERY_TERMS
