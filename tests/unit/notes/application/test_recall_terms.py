"""Turning a task sentence into search keywords."""

import pytest

from noesis.bounded_context.notes.application.mappers import recall_terms
from noesis.exceptions import ApplicationException, NoRecallTermsError

pytestmark = pytest.mark.unit


def test_keeps_lowercase_keywords_in_order() -> None:
    assert recall_terms("Fix the Login Cache bug") == "fix login cache bug"


def test_drops_short_tokens_and_stopwords() -> None:
    assert recall_terms("how to add a TTL to the cache") == "add ttl cache"


def test_removes_duplicates_keeping_the_first() -> None:
    assert recall_terms("cache Cache CACHE login cache") == "cache login"


def test_punctuation_separates_words() -> None:
    assert recall_terms("login-cache, (redis); done!") == "login cache redis done"


@pytest.mark.parametrize("task", ["the and of", "a b", "  ", "!!! ???"])
def test_no_keywords_left_is_a_typed_application_error(task: str) -> None:
    with pytest.raises(NoRecallTermsError) as raised:
        recall_terms(task)

    assert isinstance(raised.value, ApplicationException)
    assert raised.value.error_code == "NOTES_204_NO_RECALL_TERMS"
    assert raised.value.metadata == {"task": task}
    assert raised.value.next_steps
