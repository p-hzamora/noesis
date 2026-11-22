"""Scoring an installed artifact against search terms (WP-09)."""

import pytest

from noesis.bounded_context.knowledge.application.policies.catalog.overlay_match import (
    score_artifact,
    search_words,
)

pytestmark = pytest.mark.unit


def test_search_words_are_distinct_lowercase_alphanumerics() -> None:
    assert search_words("Python-Suite:DDD_cli", "cli tool") == (
        "python",
        "suite",
        "ddd",
        "cli",
        "tool",
    )


def test_name_match_outranks_description_match() -> None:
    by_name = score_artifact("plug:cli-builder", "Builds things", ("cli",))
    by_description = score_artifact("plug:builder", "Makes a cli", ("cli",))

    assert by_name == 1.0
    assert by_description == 0.5


def test_score_is_the_mean_over_terms() -> None:
    assert score_artifact("plug:cli", "Builds", ("cli", "zzz")) == 0.5


@pytest.mark.parametrize("terms", [(), ("nothing",)])
def test_no_terms_or_no_match_scores_zero(terms: tuple[str, ...]) -> None:
    assert score_artifact("plug:cli", "Builds a thing", terms) == 0.0


def test_a_term_matches_whole_words_only() -> None:
    assert score_artifact("plug:client", "A client", ("cli",)) == 0.0


def test_missing_description_is_fine() -> None:
    assert score_artifact("plug:cli", None, ("cli",)) == 1.0
