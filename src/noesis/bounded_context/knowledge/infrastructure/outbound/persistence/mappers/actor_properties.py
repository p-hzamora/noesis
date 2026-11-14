"""An `Actor` as flat `actor_*` properties (Neo4j properties cannot be maps)."""

from noesis.bounded_context.knowledge.domain.value_objects import Actor, ActorKindEnum

from .node_properties import NodeProperties


def to_actor_properties(actor: Actor) -> NodeProperties:
    """`actor_kind`, `actor_name` and `actor_session` (None when unknown)."""
    return {
        "actor_kind": actor.kind.value,
        "actor_name": actor.name,
        "actor_session": actor.session,
    }


def to_actor(node: NodeProperties) -> Actor:
    """The actor stored in a node's `actor_*` properties."""
    return Actor(
        kind=ActorKindEnum(node["actor_kind"]),
        name=node["actor_name"],
        session=node.get("actor_session"),
    )
