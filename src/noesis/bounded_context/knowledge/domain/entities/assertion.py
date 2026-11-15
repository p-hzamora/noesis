"""The Assertion aggregate: an immutable statement with a review state."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.entities.review_decision import (
    ReviewDecision,
    decide,
)
from noesis.bounded_context.knowledge.domain.events import (
    AssertionAccepted,
    AssertionProposed,
    AssertionRetracted,
    RecordSuperseded,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import InvalidAssertionError, InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Assertion(AggregateRoot["Assertion"]):
    """A judgment about two records. The statement is immutable; only review state changes.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        predicate: How subject relates to object.
        subject_id: Subject record.
        object_id: Object record.
        evidence_ids: Records that evidence it.
        rationale: Why (after redaction).
        actor: Who asserted it.
        applicability: Project and tags it applies to.
        status: Review state, `proposed` at creation.
        source_ids: What it rests on; at least one.
        subject_at_revision: Subject revision judged; None for types without revisions.
        object_at_revision: Object revision judged; None for types without revisions.
        decision_seq: Number of review decisions taken; the concurrency token.
        superseded_by_assertion_id: The `supersedes` assertion that superseded it.
        latest_decision: The latest review decision.
    """

    id: RecordId
    space_id: SpaceId
    predicate: AssertionPredicateEnum
    subject_id: RecordId
    object_id: RecordId
    evidence_ids: tuple[RecordId, ...] = ()
    rationale: str
    actor: Actor
    applicability: Applicability
    status: RecordStatusEnum
    source_ids: tuple[RecordId, ...]
    subject_at_revision: int | None = None
    object_at_revision: int | None = None
    decision_seq: int = 0
    superseded_by_assertion_id: RecordId | None = None
    latest_decision: ReviewDecision | None = None

    @classmethod
    def create(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        predicate: AssertionPredicateEnum,
        subject_id: RecordId,
        object_id: RecordId,
        evidence_ids: tuple[RecordId, ...] = (),
        rationale: str,
        actor: Actor,
        applicability: Applicability,
        source_ids: tuple[RecordId, ...],
        now: datetime,
    ) -> Self:
        """Propose an assertion.

        Raises:
            InvalidRecordError: No source.

        Returns:
            The assertion, `proposed`, with `AssertionProposed` pending.
        """
        if not source_ids:
            raise InvalidRecordError("An assertion needs at least one source.")
        assertion: Self = cls(
            id=id,
            space_id=space_id,
            predicate=predicate,
            subject_id=subject_id,
            object_id=object_id,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            rationale=rationale,
            actor=actor,
            applicability=applicability,
            status=RecordStatusEnum.PROPOSED,
            source_ids=tuple(dict.fromkeys(source_ids)),
            created_at=now,
            updated_at=now,
        )
        assertion._record(AssertionProposed(aggregate_id=id.value, space_id=space_id.value))
        return assertion

    @classmethod
    def propose(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        predicate: AssertionPredicateEnum,
        subject_id: RecordId,
        object_id: RecordId,
        subject_at_revision: int | None,
        object_at_revision: int | None,
        evidence_ids: tuple[RecordId, ...] = (),
        rationale: str,
        actor: Actor,
        applicability: Applicability,
        source_ids: tuple[RecordId, ...],
        now: datetime,
    ) -> Self:
        """Propose an assertion after checking every creation invariant.

        Raises:
            InvalidAssertionError: Subject equals object, a blank rationale, no source, or the
                object among the evidence; the metadata names the field.

        Returns:
            The assertion, `proposed`, with `AssertionProposed` pending.
        """
        cls.check_creation(
            subject_id=subject_id,
            object_id=object_id,
            rationale=rationale,
            source_count=len(source_ids),
            evidence_ids=evidence_ids,
        )
        assertion: Self = cls.create(
            id=id,
            space_id=space_id,
            predicate=predicate,
            subject_id=subject_id,
            object_id=object_id,
            evidence_ids=evidence_ids,
            rationale=rationale,
            actor=actor,
            applicability=applicability,
            source_ids=source_ids,
            now=now,
        )
        assertion.subject_at_revision = subject_at_revision
        assertion.object_at_revision = object_at_revision
        return assertion

    @staticmethod
    def check_creation(
        *,
        subject_id: RecordId,
        object_id: RecordId,
        rationale: str,
        source_count: int,
        evidence_ids: tuple[RecordId, ...],
    ) -> None:
        """Check the creation invariants that need no lookup, so a caller can fail before writing.

        Raises:
            InvalidAssertionError: Subject equals object, a blank rationale, no source, or the
                object among the evidence; the metadata names the field.
        """
        if subject_id == object_id:
            raise InvalidAssertionError(
                "An assertion's subject and object must differ.",
                {"field": "object"},
                next_steps=["Choose a different object."],
            )
        if not rationale.strip():
            raise InvalidAssertionError(
                "An assertion needs a rationale.",
                {"field": "rationale"},
                next_steps=["Pass --rationale."],
            )
        if source_count == 0:
            raise InvalidAssertionError(
                "An assertion needs at least one source.",
                {"field": "sources"},
                next_steps=["Pass at least one --source."],
            )
        if object_id in evidence_ids:
            raise InvalidAssertionError(
                "The object of an assertion cannot be its own evidence.",
                {"field": "evidence"},
                next_steps=["Remove the object from the evidence."],
            )

    def accept(
        self, *, actor: Actor, reason: str | None, basis: DecisionBasisEnum, now: datetime
    ) -> ReviewDecision:
        """Accept a proposed assertion.

        Raises:
            InvalidStatusTransitionError: The status is not `proposed`.

        Returns:
            The decision, with `AssertionAccepted` pending.
        """
        decision: ReviewDecision = self._decide(
            ReviewTransitionEnum.ACCEPT, actor=actor, reason=reason, basis=basis, now=now
        )
        self._record(AssertionAccepted(aggregate_id=self.id.value, space_id=self.space_id.value))
        return decision

    def reject(
        self, *, actor: Actor, reason: str | None, basis: DecisionBasisEnum, now: datetime
    ) -> ReviewDecision:
        """Reject a proposal: `proposed` to `retracted`.

        Raises:
            InvalidStatusTransitionError: The status is not `proposed`.
        """
        return self._retire(ReviewTransitionEnum.REJECT, actor, reason, basis, now)

    def retract(
        self, *, actor: Actor, reason: str | None, basis: DecisionBasisEnum, now: datetime
    ) -> ReviewDecision:
        """Retract an accepted assertion: `accepted` to `retracted`.

        Raises:
            InvalidStatusTransitionError: The status is not `accepted`.
        """
        return self._retire(ReviewTransitionEnum.RETRACT, actor, reason, basis, now)

    def supersede(
        self, *, cause: RecordId, successor: RecordId, actor: Actor, now: datetime
    ) -> ReviewDecision:
        """Mark an accepted assertion superseded by the accepted `supersedes` assertion `cause`.

        Raises:
            InvalidStatusTransitionError: The status is not `accepted`.
        """
        decision: ReviewDecision = self._decide(
            ReviewTransitionEnum.SUPERSEDE,
            actor=actor,
            reason=f"superseded by {successor.value}",
            basis=DecisionBasisEnum.SUPERSESSION_EFFECT,
            now=now,
            cause_assertion_id=cause,
        )
        self.superseded_by_assertion_id = cause
        self._record(
            RecordSuperseded(
                aggregate_id=self.id.value,
                space_id=self.space_id.value,
                cause_assertion_id=cause.value,
            )
        )
        return decision

    def _retire(
        self,
        transition: ReviewTransitionEnum,
        actor: Actor,
        reason: str | None,
        basis: DecisionBasisEnum,
        now: datetime,
    ) -> ReviewDecision:
        decision: ReviewDecision = self._decide(
            transition, actor=actor, reason=reason, basis=basis, now=now
        )
        self._record(AssertionRetracted(aggregate_id=self.id.value, space_id=self.space_id.value))
        return decision

    def _decide(
        self,
        transition: ReviewTransitionEnum,
        *,
        actor: Actor,
        reason: str | None,
        basis: DecisionBasisEnum,
        now: datetime,
        cause_assertion_id: RecordId | None = None,
    ) -> ReviewDecision:
        decision: ReviewDecision = decide(
            transition=transition,
            status=self.status,
            decision_seq=self.decision_seq,
            actor=actor,
            reason=reason,
            basis=basis,
            now=now,
            cause_assertion_id=cause_assertion_id,
        )
        self.status = decision.to_status
        self.decision_seq = decision.seq
        self.latest_decision = decision
        self.updated_at = now
        return decision
