"""The Knowledge aggregate: a proposition with immutable, gap-free revisions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.entities.review_decision import (
    ReviewDecision,
    decide,
)
from noesis.bounded_context.knowledge.domain.events import (
    KnowledgeAccepted,
    KnowledgeProposed,
    KnowledgeRetracted,
    KnowledgeRevised,
    RecordSuperseded,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    FileContent,
    GraphContent,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Revision,
    RevisionContent,
    Slug,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.review_lifecycle import ReviewLifecycle
from noesis.exceptions import InvalidRecordError, KnowledgeNotRevisableError, RevisionConflictError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Knowledge(AggregateRoot["Knowledge"]):
    """Knowledge with fixed ownership, a status, and its head revision.

    Invariants: ownership and space never change; a graph-owned revision carries text, a
    file-owned one only hash, file_version source id and title; revisions are numbered 1..n and
    each names an actor and at least one source; the root holds only the head; status is
    `proposed` at creation and `revise` is allowed only while it is. Review transitions follow `ReviewLifecycle`.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        ownership: `file` or `graph`, fixed.
        subtype: Open validated slug (`decision`, `gotcha`, ...).
        applicability: Project and tags it applies to.
        status: Review state.
        head: The latest revision.
        decision_seq: Number of review decisions taken; the concurrency token.
        superseded_by_assertion_id: The `supersedes` assertion that superseded it.
        latest_decision: The latest review decision.
    """

    id: RecordId
    space_id: SpaceId
    ownership: OwnershipEnum
    subtype: Slug
    applicability: Applicability
    status: RecordStatusEnum
    head: Revision
    decision_seq: int = 0
    superseded_by_assertion_id: RecordId | None = None
    latest_decision: ReviewDecision | None = None

    @property
    def head_number(self) -> int:
        """Number of the head revision."""
        return self.head.number

    @classmethod
    def create(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        ownership: OwnershipEnum,
        subtype: Slug,
        applicability: Applicability,
        actor: Actor,
        source_ids: tuple[RecordId, ...],
        content: RevisionContent,
        now: datetime,
    ) -> Self:
        """Propose knowledge: revision 1, status `proposed`.

        Raises:
            InvalidRecordError: The content shape does not match the ownership, or no source.

        Returns:
            The record with `KnowledgeProposed` pending.
        """
        _check_shape(ownership, content)
        head: Revision = Revision(
            number=1,
            actor=actor,
            source_ids=tuple(dict.fromkeys(source_ids)),
            created_at=now,
            content=content,
        )
        knowledge: Self = cls(
            id=id,
            space_id=space_id,
            ownership=ownership,
            subtype=subtype,
            applicability=applicability,
            status=RecordStatusEnum.PROPOSED,
            head=head,
            created_at=now,
            updated_at=now,
        )
        knowledge._record(
            KnowledgeProposed(
                aggregate_id=id.value, space_id=space_id.value, ownership=ownership, revision=1
            )
        )
        return knowledge

    def revise(
        self,
        *,
        expected_revision: int,
        actor: Actor,
        source_ids: tuple[RecordId, ...],
        content: GraphContent,
        now: datetime,
    ) -> Revision:
        """Append revision n+1 to graph-owned knowledge that is still `proposed`.

        The status is checked before the head, so a caller learns first that revising is closed.

        Args:
            expected_revision: The head number the caller based the change on.
            actor: Who revises.
            source_ids: Sources of the new revision; at least one.
            content: The new text.
            now: Revision time.

        Raises:
            InvalidRecordError: The record is file-owned.
            KnowledgeNotRevisableError: The status is not `proposed`.
            RevisionConflictError: `expected_revision` is not the head.

        Returns:
            The new head, with `KnowledgeRevised` pending.
        """
        if self.ownership is not OwnershipEnum.GRAPH:
            raise InvalidRecordError(
                "File-owned knowledge has no editable text; register a new file version instead.",
                {"record_id": self.id.value},
            )
        if self.status is not RecordStatusEnum.PROPOSED:
            raise KnowledgeNotRevisableError(
                f"Knowledge {self.id.value} is {self.status.value}; only proposed knowledge can be revised.",
                {"record_id": self.id.value, "status": self.status.value},
            )
        if expected_revision != self.head.number:
            raise RevisionConflictError(
                f"Expected revision {expected_revision} but the head is {self.head.number}.",
                {
                    "record_id": self.id.value,
                    "expected_revision": expected_revision,
                    "actual_revision": self.head.number,
                },
                next_steps=["Run `noesis record get`, re-apply the change, retry."],
            )
        revision: Revision = Revision(
            number=self.head.number + 1,
            actor=actor,
            source_ids=tuple(dict.fromkeys(source_ids)),
            created_at=now,
            content=content,
        )
        self.head = revision
        self.updated_at = now
        self._record(
            KnowledgeRevised(
                aggregate_id=self.id.value, space_id=self.space_id.value, revision=revision.number
            )
        )
        return revision

    def accept(
        self,
        *,
        expected_revision: int,
        actor: Actor,
        reason: str | None,
        basis: DecisionBasisEnum,
        now: datetime,
    ) -> ReviewDecision:
        """Accept proposed knowledge, pinning the head revision the caller judged.

        The lifecycle is checked before the revision, as `revise` does.

        Raises:
            InvalidStatusTransitionError: The status is not `proposed`.
            RevisionConflictError: `expected_revision` is not the head.

        Returns:
            The decision, with `KnowledgeAccepted` pending.
        """
        ReviewLifecycle.next_status(ReviewTransitionEnum.ACCEPT, self.status)
        if expected_revision != self.head.number:
            raise RevisionConflictError(
                f"Expected revision {expected_revision} but the head is {self.head.number}.",
                {
                    "record_id": self.id.value,
                    "expected_revision": expected_revision,
                    "actual_revision": self.head.number,
                },
                next_steps=[
                    "Run `noesis record get`, then pass the head as the expected revision."
                ],
            )
        decision: ReviewDecision = self._decide(
            ReviewTransitionEnum.ACCEPT,
            actor=actor,
            reason=reason,
            basis=basis,
            now=now,
            pinned_revision=self.head.number,
        )
        self._record(
            KnowledgeAccepted(
                aggregate_id=self.id.value,
                space_id=self.space_id.value,
                pinned_revision=self.head.number,
            )
        )
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
        """Retract accepted knowledge: `accepted` to `retracted`.

        Raises:
            InvalidStatusTransitionError: The status is not `accepted`.
        """
        return self._retire(ReviewTransitionEnum.RETRACT, actor, reason, basis, now)

    def supersede(
        self, *, cause: RecordId, successor: RecordId, actor: Actor, now: datetime
    ) -> ReviewDecision:
        """Mark accepted knowledge superseded by the accepted `supersedes` assertion `cause`.

        Args:
            cause: The `supersedes` assertion.
            successor: Its subject, for the event reader's benefit.
            actor: Who runs the effect.
            now: Decision time.

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
        self._record(KnowledgeRetracted(aggregate_id=self.id.value, space_id=self.space_id.value))
        return decision

    def _decide(
        self,
        transition: ReviewTransitionEnum,
        *,
        actor: Actor,
        reason: str | None,
        basis: DecisionBasisEnum,
        now: datetime,
        pinned_revision: int | None = None,
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
            pinned_revision=pinned_revision,
            cause_assertion_id=cause_assertion_id,
        )
        self.status = decision.to_status
        self.decision_seq = decision.seq
        self.latest_decision = decision
        self.updated_at = now
        return decision


def _check_shape(ownership: OwnershipEnum, content: RevisionContent) -> None:
    expected: type[GraphContent | FileContent] = (
        GraphContent if ownership is OwnershipEnum.GRAPH else FileContent
    )
    if not isinstance(content, expected):
        raise InvalidRecordError(
            f"A {ownership.value}-owned revision needs {expected.__name__}.",
            {"ownership": ownership.value},
        )
