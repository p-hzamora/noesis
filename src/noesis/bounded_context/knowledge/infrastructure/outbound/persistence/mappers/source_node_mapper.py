"""`Source` <-> `:Record:Source` node."""

from noesis.bounded_context.knowledge.domain.entities import Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    RecordId,
    SourceKindEnum,
    SpaceId,
)

from .node_keys import source_key
from .node_properties import NodeProperties, without_nulls


class SourceNodeMapper:
    """Maps a source to its node properties and back."""

    @staticmethod
    def to_properties(source: Source) -> NodeProperties:
        """Properties of the `:Record:Source` node."""
        return without_nulls(
            {
                "id": source.id.value,
                "space_id": source.space_id.value,
                "kind": source.kind.value,
                "locator": source.locator,
                "digest": source.digest.value if source.digest else None,
                "source_key": source_key(
                    space_id=source.space_id,
                    kind=source.kind,
                    locator=source.locator,
                    digest=source.digest,
                ),
                "observed_at": source.observed_at,
                "created_at": source.created_at,
                "updated_at": source.updated_at,
            }
        )

    @staticmethod
    def to_entity(node: NodeProperties) -> Source:
        """The source a node stores (no pending events)."""
        digest: str | None = node.get("digest")
        return Source(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            kind=SourceKindEnum(node["kind"]),
            locator=node["locator"],
            digest=ContentHash(value=digest) if digest else None,
            observed_at=node["observed_at"],
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
