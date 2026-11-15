"""`ReviewDecision` <-> `:Decision` node; the read side builds `ReviewDecisionDto`."""

from noesis.bounded_context.knowledge.application.dtos import ReviewDecisionDto
from noesis.bounded_context.knowledge.domain.entities.review_decision import ReviewDecision
from noesis.bounded_context.knowledge.domain.value_objects import RecordId

from .actor_properties import to_actor_properties
from .node_keys import decision_key
from .node_properties import NodeProperties, without_nulls


class DecisionNodeMapper:
    """Maps a decision to node properties and a stored node to its DTO."""

    @staticmethod
    def to_properties(record_id: RecordId, decision: ReviewDecision) -> NodeProperties:
        """Properties of the `:Decision` node (absent, never null, when a field does not apply)."""
        return without_nulls(
            {
                "decision_key": decision_key(record_id, decision.seq),
                "seq": decision.seq,
                "transition": decision.transition.value,
                "from_status": decision.from_status.value,
                "to_status": decision.to_status.value,
                **to_actor_properties(decision.actor),
                "reason": decision.reason,
                "basis": decision.basis.value,
                "pinned_revision": decision.pinned_revision,
                "cause_assertion_id": (
                    decision.cause_assertion_id.value if decision.cause_assertion_id else None
                ),
                "decided_at": decision.decided_at,
            }
        )

    @staticmethod
    def to_dto(node: NodeProperties) -> ReviewDecisionDto:
        """The decision a `:Decision` node stores."""
        return ReviewDecisionDto(
            seq=node["seq"],
            transition=node["transition"],
            from_status=node["from_status"],
            to_status=node["to_status"],
            actor_kind=node["actor_kind"],
            actor_name=node["actor_name"],
            actor_session=node.get("actor_session"),
            decided_at=node["decided_at"].isoformat(),
            reason=node.get("reason"),
            basis=node["basis"],
            pinned_revision=node.get("pinned_revision"),
            cause_assertion_id=node.get("cause_assertion_id"),
        )
