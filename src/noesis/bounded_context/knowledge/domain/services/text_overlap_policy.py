"""How alike two texts are, as the share of distinct words they have in common."""

import re
from typing import ClassVar, Final

_WORD: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


class TextOverlapPolicy:
    """Scores the lexical overlap of two texts in 0..1 (Jaccard over lowercase words).

    A cheap, deterministic stand-in for similarity: Retrieval ranks hits but reports no score.
    """

    MIN_WORD_LENGTH: ClassVar[int] = 2

    @staticmethod
    def words(text: str) -> frozenset[str]:
        """Distinct lowercase words of `text`, one-character words left out."""
        return frozenset(
            word
            for word in _WORD.findall(text.lower())
            if len(word) >= TextOverlapPolicy.MIN_WORD_LENGTH
        )

    @staticmethod
    def score(left: str, right: str) -> float:
        """Shared words over all distinct words of both texts; 0.0 when either has none."""
        first: frozenset[str] = TextOverlapPolicy.words(left)
        second: frozenset[str] = TextOverlapPolicy.words(right)
        union: frozenset[str] = first | second
        if not first or not second:
            return 0.0
        return len(first & second) / len(union)
