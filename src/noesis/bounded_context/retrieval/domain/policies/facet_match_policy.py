"""Which requirement facets a piece of text mentions, by whole words only."""

import re
from collections.abc import Iterable

_WORD = re.compile(r"[^\W_]+")


class FacetMatchPolicy:
    """A facet matches when every word of the facet is a whole word of the text.

    Words are the alphanumeric runs of the casefolded text, so `ddd-interface-cli` has the
    words `ddd`, `interface` and `cli`, and the facet `uv` does not match `uvicorn`. The policy
    holds no vocabulary: it compares the facet text with the text it is given.
    """

    def matched(self, facets: Iterable[str], *texts: str | None) -> frozenset[str]:
        """The facets mentioned by any of `texts`."""
        words: frozenset[str] = frozenset(
            word for text in texts if text for word in _WORD.findall(text.casefold())
        )
        found: set[str] = set()
        for facet in facets:
            parts: list[str] = _WORD.findall(facet.casefold())
            if parts and all(part in words for part in parts):
                found.add(facet)
        return frozenset(found)
