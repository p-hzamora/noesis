"""Decides which search queries a task becomes, and recall's sizing constants."""

import re

from noesis.exceptions import NoRecallTermsError

OVERFETCH_FACTOR: int = 3
OVERFETCH_CAP: int = 50
MAX_QUERIES: int = 12
PER_QUERY_CAP: int = 10
CHARS_PER_TOKEN: int = 4
MIN_TERM_LENGTH: int = 3

_TOKEN_PATTERN: re.Pattern[str] = re.compile(rf"\w{{{MIN_TERM_LENGTH},}}")
_COMPOUND_PATTERN: re.Pattern[str] = re.compile(r"\w[\w.-]*\w")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "about",
        "after",
        "all",
        "and",
        "any",
        "are",
        "but",
        "can",
        "continue",
        "could",
        "did",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "into",
        "its",
        "not",
        "now",
        "our",
        "out",
        "should",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


class RecallQueryBuilder:
    """Keyword extraction for recall: stopwords, minimum length, hyphenated names."""

    @staticmethod
    def terms(task: str) -> str:
        """The keywords of `task`: lowercase words of 3+ characters, no stopwords, no repeats.

        Args:
            task: What the agent is about to do, in a sentence.

        Returns:
            The keywords joined by spaces, in the order they first appear.

        Raises:
            NoRecallTermsError: Nothing is left once short words and stopwords are removed.
        """
        terms: list[str] = list(
            dict.fromkeys(
                token for token in _TOKEN_PATTERN.findall(task.lower()) if token not in _STOPWORDS
            )
        )
        if not terms:
            raise NoRecallTermsError(
                "The task has no keywords to search for.",
                {"task": task},
                next_steps=["Describe the task in a sentence with at least one specific word."],
            )
        return " ".join(terms)

    @staticmethod
    def queries(task: str, *, max_queries: int = MAX_QUERIES) -> tuple[str, ...]:
        """One search query per keyword of `task`, because a search wants every word of a query.

        Obsidian's simple search answers only notes that contain all the words, so the whole
        sentence as one query finds nothing. Searching the keywords one at a time and merging the
        hits finds the notes that share any of them. A hyphenated name such as `cv-generator` is
        kept whole (that is how notes write it) before its parts, so the part `cv`, too short to
        be a keyword on its own, is not lost.

        Args:
            task: What the agent is about to do, in a sentence.
            max_queries: Most queries to return, earliest keywords first.

        Returns:
            Lowercase queries without stopwords or repeats, in order of first appearance.

        Raises:
            NoRecallTermsError: Nothing is left once short words and stopwords are removed.
        """
        queries: dict[str, None] = {}
        for compound in _COMPOUND_PATTERN.findall(task.lower()):
            if len(compound) >= MIN_TERM_LENGTH and compound not in _STOPWORDS:
                queries.setdefault(compound)
            for part in _TOKEN_PATTERN.findall(compound):
                if part not in _STOPWORDS:
                    queries.setdefault(part)
        if not queries:
            raise NoRecallTermsError(
                "The task has no keywords to search for.",
                {"task": task},
                next_steps=["Describe the task in a sentence with at least one specific word."],
            )
        return tuple(queries)[:max_queries]
