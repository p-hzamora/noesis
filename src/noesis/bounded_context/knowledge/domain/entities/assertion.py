"""The Assertion aggregate (type only in C2; storage and review come with C4)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import AssertionProposed
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Assertion(AggregateRoot["Assertion"]):
    """A judgment about two records. The statement is immutable; only status will change (C4).

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
