"""Turn a note's relation entries into edges once the record pass has fixed target identities."""

from collections import Counter
from dataclasses import dataclass

from noesis.bounded_context.interop.domain.services.relation_target_index import (
    RelationTargetIndex,
)
from noesis.bounded_context.interop.domain.value_objects.vault_relation import (
    ClassifiedRelation,
    ImportedRelation,
    RawRelation,
    RejectedRelation,
    RelationClass,
)

RELATION_CLASSES: tuple[str, ...] = (
    "resolved",
    "dangling",
    "ambiguous",
    "not_imported",
    "self",
    "unknown_relation",
    "invalid_relation",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltRelationSet:
    """Edges, every entry's class and the per-class counts of one source note."""

    relations: tuple[ImportedRelation, ...]
    entries: tuple[ClassifiedRelation, ...]

    @property
    def counts(self) -> dict[str, int]:
        """One count per class, zero included."""
        counted: Counter[str] = Counter(entry.classification for entry in self.entries)
        return {name: counted[name] for name in RELATION_CLASSES}


class RelationSetBuilder:
    """Resolve, classify and de-duplicate; it creates neither records nor stubs."""

    def build(
        self,
        *,
        source: str,
        raw: tuple[RawRelation, ...],
        rejected: tuple[RejectedRelation, ...],
        index: RelationTargetIndex,
        targets: dict[str, str],
    ) -> BuiltRelationSet:
        """`targets` maps a note path to its record id (or a pending placeholder)."""
        entries: list[ClassifiedRelation] = [
            ClassifiedRelation(
                target_key=item.target_key,
                relation=item.relation,
                classification=item.classification,
            )
            for item in rejected
        ]
        edges: set[tuple[str, str]] = set()
        for item in raw:
            resolution = index.resolve(item.target_key)
            classification: RelationClass = resolution.classification
            if classification == "resolved":
                if resolution.path == source:
                    classification = "self"
                elif resolution.path not in targets:
                    classification = "not_imported"
                else:
                    edges.add((targets[resolution.path or ""], item.relation))
            entries.append(
                ClassifiedRelation(
                    target_key=item.target_key,
                    relation=item.relation,
                    classification=classification,
                    candidates=resolution.candidates,
                )
            )
        return BuiltRelationSet(
            relations=tuple(
                ImportedRelation(target_record_id=target, relation=relation)
                for target, relation in sorted(edges)
            ),
            entries=tuple(entries),
        )
