"""`Project` <-> `:Record:Project` node."""

from noesis.bounded_context.knowledge.domain.entities import Project
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId

from .node_keys import project_key
from .node_properties import NodeProperties


class ProjectNodeMapper:
    """Maps a project to its node properties and back."""

    @staticmethod
    def to_properties(project: Project) -> NodeProperties:
        """Properties of the `:Record:Project` node."""
        return {
            "id": project.id.value,
            "space_id": project.space_id.value,
            "key": project.key.value,
            "project_key": project_key(project.space_id, project.key),
            "name": project.name,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    @staticmethod
    def to_entity(node: NodeProperties) -> Project:
        """The project a node stores (no pending events)."""
        return Project(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            key=Key(value=node["key"]),
            name=node["name"],
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
