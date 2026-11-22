"""`CatalogEntry` <-> `:Record:CatalogEntry` node plus its `:Revision` nodes.

A revision stores only runtime-neutral values: `purpose`, `declared_version` (absent when
there is none), `prerequisites` as `kind:name` strings, `location`, `capabilities` (and their
`capabilities_text` for the full-text index), `manifest_digest` (absent when none), `origin`, the
entry `name` (so the full-text index can see it) and the usual envelope. Nodes written before the
discovery fields existed read with their defaults.
"""

from collections.abc import Iterable

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogEntryName,
    CatalogOriginEnum,
    CatalogRef,
    CatalogRevision,
    ContentHash,
    RecordId,
    SpaceId,
    Tag,
)

from .actor_properties import to_actor, to_actor_properties
from .node_keys import revision_key
from .node_properties import NodeProperties, without_nulls


class CatalogEntryNodeMapper:
    """Maps catalog entries and their revisions to node properties and back."""

    @staticmethod
    def to_properties(entry: CatalogEntry) -> NodeProperties:
        """Properties of the `:Record:CatalogEntry` node (head number, never the content)."""
        return {
            "id": entry.id.value,
            "space_id": entry.space_id.value,
            "entry_kind": entry.kind.value,
            "name": entry.name.value,
            "catalog_key": entry.catalog_key,
            "head_revision": entry.head_number,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }

    @staticmethod
    def to_revision_properties(
        record_id: RecordId, name: CatalogEntryName, revision: CatalogRevision
    ) -> NodeProperties:
        """Properties of one `:Revision:CatalogRevision` node of the entry called `name`."""
        capabilities: list[str] = sorted(tag.value for tag in revision.capabilities)
        return without_nulls(
            {
                "name": name.value,
                "revision_key": revision_key(record_id, revision.number),
                "record_id": record_id.value,
                "number": revision.number,
                "purpose": revision.purpose,
                "declared_version": revision.version,
                "prerequisites": [ref.as_text() for ref in revision.prerequisites],
                "location": revision.location,
                "capabilities": capabilities,
                "capabilities_text": " ".join(capabilities),
                "manifest_digest": revision.manifest_digest.value
                if revision.manifest_digest
                else None,
                "origin": revision.origin.value,
                "source_ids": [source_id.value for source_id in revision.source_ids],
                "created_at": revision.created_at,
                **to_actor_properties(revision.actor),
            }
        )

    @staticmethod
    def to_revision(node: NodeProperties) -> CatalogRevision:
        """The revision a `:Revision` node stores."""
        return CatalogRevision(
            number=node["number"],
            purpose=node["purpose"],
            version=node.get("declared_version"),
            prerequisites=tuple(CatalogRef.parse(text) for text in node["prerequisites"]),
            location=node["location"],
            actor=to_actor(node),
            source_ids=tuple(RecordId(value=source_id) for source_id in node["source_ids"]),
            created_at=node["created_at"],
            capabilities=frozenset(Tag(value=tag) for tag in node.get("capabilities") or ()),
            manifest_digest=ContentHash(value=digest)
            if (digest := node.get("manifest_digest"))
            else None,
            origin=CatalogOriginEnum(node.get("origin") or CatalogOriginEnum.REGISTERED),
        )

    @staticmethod
    def to_entity(node: NodeProperties, revisions: Iterable[NodeProperties]) -> CatalogEntry:
        """The entry a node and its revision nodes store (no pending events)."""
        return CatalogEntry(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            kind=CatalogEntryKindEnum(node["entry_kind"]),
            name=CatalogEntryName(value=node["name"]),
            revisions=tuple(
                CatalogEntryNodeMapper.to_revision(item)
                for item in sorted(revisions, key=lambda item: item["number"])
            ),
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
