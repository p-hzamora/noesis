"""Pure rules of a consolidation: who may be a member, which dismissals still hold, progress."""

from collections.abc import Mapping, Sequence

from noesis.bounded_context.knowledge.domain.entities.consolidation import (
    MAX_MEMBERS,
    MIN_MEMBERS,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    MIGRATED_TAG,
    ConsolidationMember,
    ConsolidationProgressEnum,
    DismissedPair,
    MemberCandidate,
    RecordStatusEnum,
)
from noesis.exceptions import IneligibleConsolidationMemberError, InvalidConsolidationError

MIGRATED_REVIEW_STEP: str = "noesis review accept --tag origin:migrated --all --yes"
"""What the user runs to review migrated proposals; the application never runs it."""


def ineligible(
    candidate: MemberCandidate, cause: str, message: str
) -> IneligibleConsolidationMemberError:
    """The eligibility error for one member; a proposed migrated record gets the review step."""
    steps: list[str] = ["Choose accepted, current Knowledge of one subtype and one project."]
    if cause == "not_accepted" and MIGRATED_TAG in candidate.tags:
        steps = [
            "Migrated records need review first: the user runs "
            f"`{MIGRATED_REVIEW_STEP}` in a terminal."
        ]
    return IneligibleConsolidationMemberError(
        message,
        {"member_id": candidate.record_id.value, "cause": cause},
        next_steps=steps,
    )


class ConsolidationEligibilityPolicy:
    """Two to ten distinct accepted Knowledge records of one subtype and one project."""

    @staticmethod
    def check_ids(ids: Sequence[str]) -> None:
        """Refuse fewer than two or more than ten ids, or a repeated id.

        Raises:
            InvalidConsolidationError: The member list has the wrong size or a repeat.
        """
        if not MIN_MEMBERS <= len(ids) <= MAX_MEMBERS:
            raise InvalidConsolidationError(
                f"A consolidation needs {MIN_MEMBERS} to {MAX_MEMBERS} members, got {len(ids)}.",
                {"member_count": len(ids)},
                next_steps=[f"Pass {MIN_MEMBERS} to {MAX_MEMBERS} distinct accepted records."],
            )
        if len(set(ids)) != len(ids):
            raise InvalidConsolidationError(
                "A consolidation member appears more than once.",
                next_steps=["Name each original once."],
            )

    @staticmethod
    def check(candidates: Sequence[MemberCandidate]) -> tuple[ConsolidationMember, ...]:
        """Validate the candidates and pin each at its head revision.

        Raises:
            InvalidConsolidationError: Fewer than two or more than ten, or a repeat.
            IneligibleConsolidationMemberError: A member is unknown, not Knowledge, not accepted,
                superseded or retracted, or differs in subtype or project; the metadata names
                the member and the cause.

        Returns:
            The members in ascending record id.
        """
        ConsolidationEligibilityPolicy.check_ids([c.record_id.value for c in candidates])
        ordered: list[MemberCandidate] = sorted(candidates, key=lambda c: c.record_id.value)
        for candidate in ordered:
            ConsolidationEligibilityPolicy._check_one(candidate)
        first: MemberCandidate = ordered[0]
        for candidate in ordered[1:]:
            if candidate.subtype != first.subtype:
                raise ineligible(candidate, "subtype_mismatch", "Members must share one subtype.")
            if candidate.project_id != first.project_id:
                raise ineligible(
                    candidate,
                    "project_mismatch",
                    "Members must share one project (or all be space-wide).",
                )
        return tuple(
            ConsolidationMember(record_id=c.record_id, at_revision=c.head_revision or 1)
            for c in ordered
        )

    @staticmethod
    def _check_one(candidate: MemberCandidate) -> None:
        name: str = candidate.record_id.value
        if not candidate.found:
            raise ineligible(candidate, "not_found", f"No record {name} in this space.")
        if not candidate.is_knowledge:
            raise ineligible(candidate, "not_knowledge", f"{name} is not a Knowledge record.")
        status: RecordStatusEnum | None = candidate.effective_status
        if status is RecordStatusEnum.ACCEPTED:
            return
        cause: str = (
            "not_accepted"
            if status is RecordStatusEnum.PROPOSED
            else status.value
            if status is not None
            else "unknown"
        )
        raise ineligible(
            candidate,
            cause,
            f"Knowledge {name} is {status.value if status else 'unknown'}; only accepted, "
            "current Knowledge can be consolidated.",
        )


class DismissedPairPolicy:
    """A `distinct` dismissal suppresses a pair only while both revisions are the ones judged."""

    @staticmethod
    def suppressing(
        pairs: Sequence[DismissedPair], revisions: Mapping[str, int]
    ) -> list[DismissedPair]:
        """The pairs whose judged revisions are the current ones."""
        return [
            pair
            for pair in pairs
            if revisions.get(pair.first_id) == pair.first_revision
            and revisions.get(pair.second_id) == pair.second_revision
        ]


class ConsolidationProgressPolicy:
    """Progress is derived from review state; the aggregate's state is only orchestration history."""

    @staticmethod
    def derive(
        *,
        materialised: bool,
        successor_status: str | None,
        assertion_statuses: Sequence[str | None],
        member_statuses: Sequence[str | None],
    ) -> ConsolidationProgressEnum:
        """`successor_retracted`, else `applied`, `pending` or `partially_applied`.

        `applied` needs an accepted successor, every assertion accepted and every original
        effectively superseded; `pending` means nothing was accepted yet.
        """
        if not materialised:
            return ConsolidationProgressEnum.PENDING
        if successor_status == RecordStatusEnum.RETRACTED.value:
            return ConsolidationProgressEnum.SUCCESSOR_RETRACTED
        accepted = RecordStatusEnum.ACCEPTED.value
        superseded = RecordStatusEnum.SUPERSEDED.value
        if (
            successor_status == accepted
            and all(status == accepted for status in assertion_statuses)
            and all(status == superseded for status in member_statuses)
        ):
            return ConsolidationProgressEnum.APPLIED
        if successor_status != accepted and all(s != accepted for s in assertion_statuses):
            return ConsolidationProgressEnum.PENDING
        return ConsolidationProgressEnum.PARTIALLY_APPLIED
