"""Requirement facets from explicit needs, else salient query terms; no topic vocabulary."""

import re
from collections.abc import Iterable

from ..enums import RequirementSourceEnum
from ..value_objects.requirement_facet import RequirementFacet
from .identifier_query_policy import IdentifierQueryPolicy

_TOKEN = re.compile(r"[\w][\w./\\-]*")
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "not", "no", "of", "to", "in", "on", "at", "by",
        "for", "with", "from", "into", "as", "is", "are", "was", "were", "be", "been", "being",
        "do", "does", "did", "how", "what", "why", "when", "where", "which", "who", "i", "we",
        "you", "it", "this", "that", "these", "those", "my", "our", "your", "me", "us", "can",
        "could", "should", "would", "will", "shall", "may", "might", "must", "need", "want",
        "please", "some", "any", "about", "so", "if", "then", "than", "also", "just", "use",
    }
)  # fmt: skip
MAX_QUERY_TERMS = 8
"""Upper bound on facets taken from a query, so one long sentence cannot flood selection."""


class RequirementExtractionPolicy:
    """Facets are the explicit needs when given, otherwise the query's salient terms.

    A term is salient when it is an identifier-like token or a word of two characters or
    more that is not a grammar stop word. Nothing here knows any subject matter.
    """

    def __init__(self, identifiers: IdentifierQueryPolicy | None = None) -> None:
        self._identifiers = identifiers or IdentifierQueryPolicy()

    def extract(self, query: str, needs: tuple[str, ...] = ()) -> tuple[RequirementFacet, ...]:
        """Facets in first-seen order, without duplicates."""
        explicit = self._unique(need.strip() for need in needs)
        if explicit:
            return tuple(
                RequirementFacet(id=item, source=RequirementSourceEnum.NEED) for item in explicit
            )
        terms = self._unique(self._salient(query))[:MAX_QUERY_TERMS]
        return tuple(
            RequirementFacet(id=item, source=RequirementSourceEnum.QUERY) for item in terms
        )

    def _salient(self, query: str) -> list[str]:
        found: list[str] = []
        for match in _TOKEN.finditer(query):
            token = match.group(0).rstrip(".-/\\")
            if not token:
                continue
            if self._identifiers.is_identifier(token):
                found.append(token)
                continue
            word = token.casefold()
            if len(word) >= 2 and word not in _STOP_WORDS:
                found.append(word)
        return found

    @staticmethod
    def _unique(items: Iterable[str]) -> list[str]:
        seen: dict[str, None] = {}
        for item in items:
            if item:
                seen.setdefault(item.casefold(), None)
        return list(seen)
