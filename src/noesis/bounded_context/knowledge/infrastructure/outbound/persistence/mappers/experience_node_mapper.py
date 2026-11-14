"""`Experience` <-> `:Record:Experience` node."""

from noesis.bounded_context.knowledge.domain.entities import Experience
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    RecordId,
    SpaceId,
)

from .actor_properties import to_actor, to_actor_properties
from .node_properties import NodeProperties, without_nulls


class ExperienceNodeMapper:
    """Maps an experience to its node properties and back."""

    @staticmethod
    def to_properties(experience: Experience) -> NodeProperties:
        """Properties of the `:Record:Experience` node."""
        return without_nulls(
            {
                "id": experience.id.value,
                "space_id": experience.space_id.value,
                "project_id": experience.project_id.value if experience.project_id else None,
                "subtype": experience.subtype.value,
                "body": experience.body,
                "occurred_at": experience.occurred_at,
                "session": experience.session,
                "environment": experience.environment,
                "source_ids": [source_id.value for source_id in experience.source_ids],
                "created_at": experience.created_at,
                "updated_at": experience.updated_at,
                **to_actor_properties(experience.actor),
            }
        )

    @staticmethod
    def to_entity(node: NodeProperties) -> Experience:
        """The experience a node stores (no pending events)."""
        project_id: str | None = node.get("project_id")
        return Experience(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            project_id=RecordId(value=project_id) if project_id else None,
            subtype=ExperienceSubtypeEnum(node["subtype"]),
            body=node["body"],
            occurred_at=node["occurred_at"],
            session=node.get("session"),
            environment=node.get("environment"),
            actor=to_actor(node),
            source_ids=tuple(RecordId(value=source_id) for source_id in node["source_ids"]),
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
