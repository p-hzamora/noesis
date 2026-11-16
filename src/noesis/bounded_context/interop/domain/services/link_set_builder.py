"""Group resolved occurrences after the record pass establishes target identities."""

from collections import Counter
from dataclasses import dataclass, replace

from noesis.bounded_context.interop.domain.value_objects.vault_link import (
    ImportedLink,
    LinkType,
    ResolvedLink,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltLinkSet:
    """Edges and reclassified occurrences for one source note."""

    links: tuple[ImportedLink, ...]
    occurrences: tuple[ResolvedLink, ...]


class LinkSetBuilder:
    """Count occurrences and retain sorted distinct non-empty anchors."""

    def build(self, occurrences: tuple[ResolvedLink, ...], targets: dict[str, str]) -> BuiltLinkSet:
        """Reclassify unavailable targets before building edges."""
        counts: Counter[tuple[str, LinkType]] = Counter()
        anchors: dict[tuple[str, LinkType], set[str]] = {}
        classified: list[ResolvedLink] = []
        for occurrence in occurrences:
            if occurrence.classification == "resolved":
                target: str | None = targets.get(occurrence.path or "")
                if target is None:
                    occurrence = replace(occurrence, classification="not_imported")
                else:
                    key: tuple[str, LinkType] = (
                        target,
                        "embeds" if occurrence.link.embed else "links_to",
                    )
                    counts[key] += 1
                    anchors.setdefault(key, set())
                    if occurrence.link.anchor:
                        anchors[key].add(occurrence.link.anchor)
            classified.append(occurrence)
        return BuiltLinkSet(
            links=tuple(
                ImportedLink(
                    target_record_id=target,
                    link_type=kind,
                    count=count,
                    anchors=tuple(sorted(anchors[(target, kind)])),
                )
                for (target, kind), count in sorted(counts.items())
            ),
            occurrences=tuple(classified),
        )
