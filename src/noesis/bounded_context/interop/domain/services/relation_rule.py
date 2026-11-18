"""Which `related` entries of a header are well-formed relations with a known word."""

from collections.abc import Mapping
from dataclasses import dataclass

from noesis.bounded_context.interop.domain.value_objects.vault_relation import (
    RawRelation,
    RejectedRelation,
)

RELATION_WORDS: frozenset[str] = frozenset(
    {
        "refines",
        "part_of",
        "contains",
        "implements",
        "consumes",
        "extends",
        "contradicts",
        "supersedes",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RelationParseResult:
    """What the rule made of a `related` value.

    Attributes:
        relations: Entries with a known word, in header order.
        rejected: Entries (or the whole value) that cannot become edges.
    """

    relations: tuple[RawRelation, ...]
    rejected: tuple[RejectedRelation, ...]


def _scalar(value: object) -> str | None:
    """A scalar as trimmed text; None for absent, blank or structured values."""
    if value is None or isinstance(value, Mapping | list | tuple | set):
        return None
    return str(value).strip() or None


class RelationRule:
    """Parses `related: [{id, relation}]`; words pass through unchanged."""

    def parse(self, value: object) -> RelationParseResult:
        """Parse the `related` value of a header (None when absent)."""
        if value is None:
            return RelationParseResult(relations=(), rejected=())
        if not isinstance(value, list):
            return RelationParseResult(
                relations=(),
                rejected=(
                    RejectedRelation(classification="invalid_relation", target_key="", relation=""),
                ),
            )
        found: list[RawRelation] = []
        rejected: list[RejectedRelation] = []
        for entry in value:
            target: str | None = _scalar(entry.get("id")) if isinstance(entry, Mapping) else None
            word: str | None = (
                _scalar(entry.get("relation")) if isinstance(entry, Mapping) else None
            )
            if target is None or word is None:
                rejected.append(
                    RejectedRelation(
                        classification="invalid_relation",
                        target_key=target or "",
                        relation=word or "",
                    )
                )
            elif word not in RELATION_WORDS:
                rejected.append(
                    RejectedRelation(
                        classification="unknown_relation", target_key=target, relation=word
                    )
                )
            else:
                found.append(RawRelation(target_key=target, relation=word))
        return RelationParseResult(relations=tuple(found), rejected=tuple(rejected))
