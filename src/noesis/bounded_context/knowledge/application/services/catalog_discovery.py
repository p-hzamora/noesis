"""Rules `catalog sync` and the live overlay share about what a probe found."""

from collections.abc import Iterable

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, CatalogRef
from noesis.exceptions import InvalidCatalogPrerequisiteError

NO_DESCRIPTION: str = "(no description)"
"""The purpose of a discovered entry whose manifest has no readable description."""

DISCOVERABLE_KINDS: frozenset[CatalogEntryKindEnum] = frozenset(
    {CatalogEntryKindEnum.SKILL, CatalogEntryKindEnum.AGENT}
)
"""The kinds a runtime probe finds by reading a manifest."""


def declared_prerequisites(requires: Iterable[str], *, own: CatalogRef) -> tuple[str, ...]:
    """`requires` as normalised `kind:name` texts, without repeats, malformed values or `own`."""
    kept: list[str] = []
    for text in requires:
        try:
            ref: CatalogRef = CatalogRef.parse(text)
        except InvalidCatalogPrerequisiteError:
            continue
        if ref.kind is own.kind and ref.name == own.name:
            continue
        kept.append(ref.as_text())
    return tuple(dict.fromkeys(kept))
