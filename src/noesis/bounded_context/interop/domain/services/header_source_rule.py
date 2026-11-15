"""Q-014: which `noesis.sources` entries become extra Sources."""

import re
from dataclasses import dataclass

from noesis.bounded_context.interop.domain.value_objects import HeaderSource

COMMIT_SHA: re.Pattern[str] = re.compile(r"^[0-9a-fA-F]{40}$")
PREFIX_KINDS: dict[str, str] = {
    "commit": "commit",
    "session": "agent_session",
    "url": "url",
    "work_brief": "work_brief",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class HeaderSourceResult:
    """What the rule made of a `sources` value.

    Attributes:
        sources: Mappable entries in header order, de-duplicated.
        skipped: Entries (or the whole value) that did not map.
    """

    sources: tuple[HeaderSource, ...]
    skipped: int


class HeaderSourceRule:
    """Maps `<prefix>:<value>` strings to Source kinds; everything else is skipped and counted."""

    def map(self, value: object) -> HeaderSourceResult:
        """Map the `sources` value of the `noesis` block (None when absent)."""
        if value is None:
            return HeaderSourceResult(sources=(), skipped=0)
        if not isinstance(value, list):
            return HeaderSourceResult(sources=(), skipped=1)
        found: list[HeaderSource] = []
        skipped: int = 0
        for entry in value:
            source: HeaderSource | None = self._entry(entry)
            if source is None:
                skipped += 1
            elif source not in found:
                found.append(source)
        return HeaderSourceResult(sources=tuple(found), skipped=skipped)

    def _entry(self, entry: object) -> HeaderSource | None:
        if not isinstance(entry, str):
            return None
        prefix, separator, rest = entry.partition(":")
        kind: str | None = PREFIX_KINDS.get(prefix.strip())
        locator: str = rest.strip()
        if kind is None or not separator or not locator:
            return None
        if kind == "commit":
            if not COMMIT_SHA.match(locator):
                return None
            locator = locator.lower()
        return HeaderSource(kind=kind, locator=locator)
