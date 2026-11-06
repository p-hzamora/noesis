"""Turn the sentence an agent is working on into search keywords, and recall's sizing constants."""

import re

from noesis.exceptions import NoRecallTermsError

OVERFETCH_FACTOR: int = 3
OVERFETCH_CAP: int = 50
CHARS_PER_TOKEN: int = 4
MIN_TERM_LENGTH: int = 3

_TOKEN_PATTERN: re.Pattern[str] = re.compile(rf"\w{{{MIN_TERM_LENGTH},}}")
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
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def recall_terms(task: str) -> str:
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
