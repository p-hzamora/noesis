"""Turning a task sentence into search keywords."""

import pytest

from noesis.bounded_context.notes.application.services.recall import RecallQueryBuilder
from noesis.exceptions import ApplicationException, NoRecallTermsError

pytestmark = pytest.mark.unit


def test_keeps_lowercase_keywords_in_order() -> None:
    assert RecallQueryBuilder.terms("Fix the Login Cache bug") == "fix login cache bug"


def test_drops_short_tokens_and_stopwords() -> None:
    assert RecallQueryBuilder.terms("how to add a TTL to the cache") == "add ttl cache"


def test_removes_duplicates_keeping_the_first() -> None:
    assert RecallQueryBuilder.terms("cache Cache CACHE login cache") == "cache login"


def test_punctuation_separates_words() -> None:
    assert RecallQueryBuilder.terms("login-cache, (redis); done!") == "login cache redis done"


@pytest.mark.parametrize("task", ["the and of", "a b", "  ", "!!! ???"])
def test_no_keywords_left_is_a_typed_application_error(task: str) -> None:
    with pytest.raises(NoRecallTermsError) as raised:
        RecallQueryBuilder.terms(task)

    assert isinstance(raised.value, ApplicationException)
    assert raised.value.error_code == "NOTES_204_NO_RECALL_TERMS"
    assert raised.value.metadata == {"task": task}
    assert raised.value.next_steps


def test_queries_are_one_per_keyword() -> None:
    assert RecallQueryBuilder.queries("Fix the Login Cache bug") == ("fix", "login", "cache", "bug")


def test_a_hyphenated_name_is_kept_whole_before_its_parts() -> None:
    queries = RecallQueryBuilder.queries(
        "Continue working on the cv-generator project while preserving candidate privacy"
    )

    assert queries[:2] == ("working", "cv-generator")
    assert "generator" in queries
    assert "cv" not in queries  # too short on its own; the whole name carries it


def test_queries_drop_stopwords_and_repeats_and_are_capped() -> None:
    assert RecallQueryBuilder.queries("cache Cache the cache") == ("cache",)
    task = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike"
    assert RecallQueryBuilder.queries(task) == tuple(task.split()[:12])
    assert RecallQueryBuilder.queries(task, max_queries=2) == ("alpha", "bravo")


@pytest.mark.parametrize("task", ["the and of", "a b", "  ", "!!! ???"])
def test_queries_without_keywords_are_a_typed_error(task: str) -> None:
    with pytest.raises(NoRecallTermsError):
        RecallQueryBuilder.queries(task)
