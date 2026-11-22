"""Scoring an installed artifact against search terms, in memory (the live overlay).

It knows no vocabulary: a term matches a word of the artifact's name or description.
"""

import re
from collections.abc import Iterable
from typing import Final

_WORD: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
NAME_WEIGHT: Final[float] = 1.0
DESCRIPTION_WEIGHT: Final[float] = 0.5


def search_words(*texts: str) -> tuple[str, ...]:
    """The distinct lowercase alphanumeric words of `texts`, in order of first appearance."""
    return tuple(dict.fromkeys(word for text in texts for word in _WORD.findall(text.lower())))


def score_artifact(name: str, description: str | None, terms: Iterable[str]) -> float:
    """Relevance in 0..1 of an artifact for `terms` (already split into words).

    Each term earns 1.0 when it is a word of the name, 0.5 when only a word of the description,
    else 0; the score is the mean over the terms. No terms, or no match, scores 0.
    """
    wanted: tuple[str, ...] = tuple(terms)
    if not wanted:
        return 0.0
    name_words: frozenset[str] = frozenset(search_words(name))
    description_words: frozenset[str] = frozenset(search_words(description or ""))
    earned: float = sum(
        NAME_WEIGHT
        if term in name_words
        else DESCRIPTION_WEIGHT
        if term in description_words
        else 0.0
        for term in wanted
    )
    return earned / len(wanted)
