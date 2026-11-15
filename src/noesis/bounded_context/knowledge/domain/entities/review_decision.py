"""One review decision: the child entity a transition appends."""

from dataclasses import dataclass
from datetime import datetime

from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    RecordId,
    RecordStatusEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.review_lifecycle import ReviewLifecycle


@dataclass(slots=True, kw_only=True, frozen=True)
class ReviewDecision:
    """What was decided about a record, by whom and why.

    Attributes:
        seq: 1..n per record; with the record id it is the decision key.
        transition: The step taken.
        from_status: Status before.
        to_status: Status after.
        actor: Who decided.
        decided_at: When.
        reason: Why; required for reject and retract.
        basis: Closed set naming the kind of decision.
        pinned_revision: Head judged (accept of Knowledge), else None.
        cause_assertion_id: The `supersedes` assertion (supersede only), else None.
    """

    seq: int
    transition: ReviewTransitionEnum
    from_status: RecordStatusEnum
    to_status: RecordStatusEnum
    actor: Actor
    decided_at: datetime
    reason: str | None
    basis: DecisionBasisEnum
    pinned_revision: int | None = None
    cause_assertion_id: RecordId | None = None


def decide(
    *,
    transition: ReviewTransitionEnum,
    status: RecordStatusEnum,
    decision_seq: int,
    actor: Actor,
    reason: str | None,
    basis: DecisionBasisEnum,
    now: datetime,
    pinned_revision: int | None = None,
    cause_assertion_id: RecordId | None = None,
) -> ReviewDecision:
    """The next decision of a record, after checking the lifecycle.

    Raises:
        InvalidStatusTransitionError: `transition` is not allowed from `status`.
    """
    return ReviewDecision(
        seq=decision_seq + 1,
        transition=transition,
        from_status=status,
        to_status=ReviewLifecycle.next_status(transition, status),
        actor=actor,
        decided_at=now,
        reason=reason,
        basis=basis,
        pinned_revision=pinned_revision,
        cause_assertion_id=cause_assertion_id,
    )
