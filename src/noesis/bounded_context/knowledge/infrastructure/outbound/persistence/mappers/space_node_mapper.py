"""`KnowledgeSpace` <-> `:Space` node."""

from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key, SpaceId

from .node_properties import NodeProperties


class SpaceNodeMapper:
    """Maps a space to its node properties and back."""

    @staticmethod
    def to_properties(space: KnowledgeSpace) -> NodeProperties:
        """Properties of the `:Space` node."""
        return {
            "id": space.id.value,
            "key": space.key.value,
            "name": space.name,
            "created_at": space.created_at,
            "updated_at": space.updated_at,
        }

    @staticmethod
    def to_entity(node: NodeProperties) -> KnowledgeSpace:
        """The space a `:Space` node stores (no pending events)."""
        return KnowledgeSpace(
            id=SpaceId(value=node["id"]),
            key=Key(value=node["key"]),
            name=node["name"],
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
