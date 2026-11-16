"""`Consolidation` <-> `:Consolidation` node and its `:ConsolidationMembership` nodes.

The node keeps the originals only as membership nodes (`<cid>:<record_id>`), whose `open_key`
is the record id while the consolidation holds it and is removed on dismissal; a uniqueness
constraint on `open_key` makes "one open consolidation per record" a database guarantee.
"""

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDismissalDto,
    ConsolidationDto,
    ConsolidationMemberDto,
)
from noesis.bounded_context.knowledge.domain.entities import Consolidation
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    ConsolidationDismissal,
    ConsolidationId,
    ConsolidationKindEnum,
    ConsolidationMember,
    ConsolidationStateEnum,
    DismissalReasonKindEnum,
    RecordId,
    SpaceId,
)

from .actor_properties import to_actor, to_actor_properties
from .node_properties import NodeProperties, without_nulls


def membership_key(consolidation_id: ConsolidationId, record_id: RecordId) -> str:
    """`ConsolidationMembership.membership_key`: `<consolidation_id>:<record_id>`."""
    return f"{consolidation_id.value}:{record_id.value}"


class ConsolidationNodeMapper:
    """Maps a consolidation to node properties and back."""

    @staticmethod
    def to_properties(consolidation: Consolidation) -> NodeProperties:
        """Properties of the `:Consolidation` node (absent, never null, when a field does not apply)."""
        dismissal: ConsolidationDismissal | None = consolidation.dismissal
        return without_nulls(
            {
                "id": consolidation.id.value,
                "space_id": consolidation.space_id.value,
                "kind": consolidation.kind.value,
                "state": consolidation.state.value,
                "fingerprint": consolidation.fingerprint,
                "rationale": consolidation.rationale,
                "project_id": consolidation.project_id.value if consolidation.project_id else None,
                "successor_id": (
                    consolidation.successor_id.value if consolidation.successor_id else None
                ),
                "produced_assertion_ids": [i.value for i in consolidation.produced_assertion_ids],
                "version": consolidation.version,
                **to_actor_properties(consolidation.created_by),
                "created_at": consolidation.created_at,
                "updated_at": consolidation.updated_at,
                "dismissal_reason_kind": dismissal.reason_kind.value if dismissal else None,
                "dismissal_reason": dismissal.reason if dismissal else None,
                "dismissal_actor_kind": dismissal.actor.kind.value if dismissal else None,
                "dismissal_actor_name": dismissal.actor.name if dismissal else None,
                "dismissal_actor_session": dismissal.actor.session if dismissal else None,
                "dismissed_at": dismissal.dismissed_at if dismissal else None,
            }
        )

    @staticmethod
    def membership_properties(
        consolidation: Consolidation, member: ConsolidationMember
    ) -> NodeProperties:
        """Properties of one `:ConsolidationMembership` node."""
        return {
            "membership_key": membership_key(consolidation.id, member.record_id),
            "open_key": member.record_id.value,
            "record_id": member.record_id.value,
            "space_id": consolidation.space_id.value,
            "consolidation_id": consolidation.id.value,
            "at_revision": member.at_revision,
        }

    @staticmethod
    def to_entity(node: NodeProperties, members: list[NodeProperties]) -> Consolidation:
        """The consolidation a node and its memberships store (no pending events)."""
        project_id: str | None = node.get("project_id")
        successor: str | None = node.get("successor_id")
        dismissal: ConsolidationDismissal | None = None
        if "dismissal_reason_kind" in node:
            dismissal = ConsolidationDismissal(
                reason_kind=DismissalReasonKindEnum(node["dismissal_reason_kind"]),
                reason=node["dismissal_reason"],
                actor=Actor(
                    kind=ActorKindEnum(node["dismissal_actor_kind"]),
                    name=node["dismissal_actor_name"],
                    session=node.get("dismissal_actor_session"),
                ),
                dismissed_at=node["dismissed_at"],
            )
        return Consolidation(
            id=ConsolidationId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            kind=ConsolidationKindEnum(node["kind"]),
            state=ConsolidationStateEnum(node["state"]),
            members=tuple(
                ConsolidationMember(
                    record_id=RecordId(value=m["record_id"]), at_revision=m["at_revision"]
                )
                for m in sorted(members, key=lambda item: item["record_id"])
            ),
            fingerprint=node["fingerprint"],
            rationale=node["rationale"],
            project_id=RecordId(value=project_id) if project_id else None,
            created_by=to_actor(node),
            version=node["version"],
            successor_id=RecordId(value=successor) if successor else None,
            produced_assertion_ids=tuple(
                RecordId(value=i) for i in node.get("produced_assertion_ids", [])
            ),
            dismissal=dismissal,
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )

    @staticmethod
    def to_dto(
        node: NodeProperties, members: list[NodeProperties], project_key: str | None
    ) -> ConsolidationDto:
        """The read model of a stored consolidation."""
        dismissal: ConsolidationDismissalDto | None = None
        if "dismissal_reason_kind" in node:
            dismissal = ConsolidationDismissalDto(
                reason_kind=node["dismissal_reason_kind"],
                reason=node["dismissal_reason"],
                actor_kind=node["dismissal_actor_kind"],
                actor_name=node["dismissal_actor_name"],
                dismissed_at=node["dismissed_at"].isoformat(),
            )
        return ConsolidationDto(
            id=node["id"],
            space_id=node["space_id"],
            kind=node["kind"],
            state=node["state"],
            fingerprint=node["fingerprint"],
            rationale=node["rationale"],
            project_key=project_key,
            successor_id=node.get("successor_id"),
            produced_assertion_ids=tuple(node.get("produced_assertion_ids", [])),
            version=node["version"],
            created_by_kind=node["actor_kind"],
            created_by_name=node["actor_name"],
            created_at=node["created_at"].isoformat(),
            members=tuple(
                ConsolidationMemberDto(record_id=m["record_id"], at_revision=m["at_revision"])
                for m in sorted(members, key=lambda item: item["record_id"])
            ),
            dismissal=dismissal,
        )
