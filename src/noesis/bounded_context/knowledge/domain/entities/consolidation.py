"""The Consolidation aggregate: bookkeeping that proposes one successor for 2..10 originals.

It is never a record: it is not searchable, not an assertion endpoint and emits no change-feed
event. Every record effect belongs to the existing Knowledge and review handlers.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ConsolidationDismissal,
    ConsolidationId,
    ConsolidationKindEnum,
    ConsolidationMember,
    ConsolidationStateEnum,
    DismissalReasonKindEnum,
    RecordId,
    SpaceId,
)
from noesis.exceptions import (
    ConsolidationClosedError,
    ConsolidationNotMaterialisedError,
    InvalidConsolidationError,
)
from noesis.shared_kernel.domain.entities import AggregateRoot

MIN_MEMBERS: int = 2
MAX_MEMBERS: int = 10


def fingerprint_of(members: tuple[ConsolidationMember, ...]) -> str:
    """`sha256:` over the sorted `id:revision` pairs; informational, never a key."""
    pairs: str = ",".join(f"{m.record_id.value}:{m.at_revision}" for m in members)
    return f"sha256:{hashlib.sha256(pairs.encode()).hexdigest()}"


@dataclass(slots=True, kw_only=True)
class Consolidation(AggregateRoot["Consolidation"]):
    """Opened, then materialised once the successor and its assertions exist, then decided.

    States: `opened` to `materialised` to `acceptance_started`; `opened` or `materialised` to
    `dismissed`. `acceptance_started` and `dismissed` exclude each other and are terminal. Each
    transition raises `version` by one; the store compares it on save.

    Attributes:
        id: Consolidation id.
        space_id: Owning space, fixed.
        kind: Always `graph_merge`.
        state: Where it is.
        members: The originals with the revision judged, ascending record id; 2..10, distinct.
        fingerprint: Hash of the member pairs (informational).
        rationale: Redacted why.
        project_id: The members' shared project; None when they are space-wide.
        created_by: Who opened it.
        version: Optimistic-concurrency token.
        successor_id: The proposed successor, once materialised.
        produced_assertion_ids: The proposed `supersedes` assertions, one per member.
        dismissal: Why it was dismissed, when it was.
    """

    id: ConsolidationId
    space_id: SpaceId
    kind: ConsolidationKindEnum = ConsolidationKindEnum.GRAPH_MERGE
    state: ConsolidationStateEnum
    members: tuple[ConsolidationMember, ...]
    fingerprint: str
    rationale: str
    project_id: RecordId | None = None
    created_by: Actor
    version: int = 1
    successor_id: RecordId | None = None
    produced_assertion_ids: tuple[RecordId, ...] = ()
    dismissal: ConsolidationDismissal | None = None

    @classmethod
    def create(
        cls,
        *,
        id: ConsolidationId,
        space_id: SpaceId,
        members: tuple[ConsolidationMember, ...],
        rationale: str,
        project_id: RecordId | None,
        actor: Actor,
        now: datetime,
    ) -> Self:
        """Open a consolidation.

        Raises:
            InvalidConsolidationError: Fewer than two or more than ten members, a repeated
                member, or a blank rationale.
        """
        ordered: tuple[ConsolidationMember, ...] = tuple(
            sorted(members, key=lambda member: member.record_id.value)
        )
        if not MIN_MEMBERS <= len(ordered) <= MAX_MEMBERS:
            raise InvalidConsolidationError(
                f"A consolidation needs {MIN_MEMBERS} to {MAX_MEMBERS} members, got {len(ordered)}.",
                {"member_count": len(ordered)},
                next_steps=[f"Pass {MIN_MEMBERS} to {MAX_MEMBERS} distinct accepted records."],
            )
        if len({m.record_id for m in ordered}) != len(ordered):
            raise InvalidConsolidationError(
                "A consolidation member appears more than once.",
                next_steps=["Name each original once."],
            )
        if not rationale.strip():
            raise InvalidConsolidationError(
                "A consolidation needs a rationale.", next_steps=["Say why they overlap."]
            )
        return cls(
            id=id,
            space_id=space_id,
            state=ConsolidationStateEnum.OPENED,
            members=ordered,
            fingerprint=fingerprint_of(ordered),
            rationale=rationale,
            project_id=project_id,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )

    def materialise(
        self, *, successor_id: RecordId, assertion_ids: tuple[RecordId, ...], now: datetime
    ) -> bool:
        """Record the proposals that exist; a repeat is a no-op.

        Raises:
            ConsolidationClosedError: It was dismissed.
            InvalidConsolidationError: The assertions are not one per member.

        Returns:
            Whether the state changed.
        """
        if self.state is ConsolidationStateEnum.DISMISSED:
            raise self._closed()
        if self.state is not ConsolidationStateEnum.OPENED:
            return False
        if len(assertion_ids) != len(self.members):
            raise InvalidConsolidationError(
                "A consolidation needs one `supersedes` assertion per member.",
                {"members": len(self.members), "assertions": len(assertion_ids)},
            )
        self.successor_id = successor_id
        self.produced_assertion_ids = assertion_ids
        self._move(ConsolidationStateEnum.MATERIALISED, now)
        return True

    def start_acceptance(self, *, now: datetime) -> bool:
        """Begin accepting the proposals; a repeat is a no-op, and this state never reopens.

        Raises:
            ConsolidationNotMaterialisedError: The proposals were never completed.
            ConsolidationClosedError: It was dismissed.

        Returns:
            Whether the state changed.
        """
        if self.state is ConsolidationStateEnum.ACCEPTANCE_STARTED:
            return False
        if self.state is ConsolidationStateEnum.DISMISSED:
            raise self._closed()
        if self.state is ConsolidationStateEnum.OPENED:
            raise ConsolidationNotMaterialisedError(
                f"Consolidation {self.id.value} was opened but its proposals are incomplete.",
                {"consolidation_id": self.id.value},
                next_steps=["Retry the propose command with the same idempotency key."],
            )
        self._move(ConsolidationStateEnum.ACCEPTANCE_STARTED, now)
        return True

    def dismiss(
        self,
        *,
        reason_kind: DismissalReasonKindEnum,
        reason: str,
        actor: Actor,
        now: datetime,
    ) -> bool:
        """Dismiss it, releasing the membership; a repeat is a no-op.

        Raises:
            ConsolidationClosedError: Acceptance already started.

        Returns:
            Whether the state changed.
        """
        if self.state is ConsolidationStateEnum.DISMISSED:
            return False
        if self.state is ConsolidationStateEnum.ACCEPTANCE_STARTED:
            raise self._closed()
        self.dismissal = ConsolidationDismissal(
            reason_kind=reason_kind, reason=reason, actor=actor, dismissed_at=now
        )
        self._move(ConsolidationStateEnum.DISMISSED, now)
        return True

    @property
    def holds_membership(self) -> bool:
        """Whether the members are reserved: everything but a dismissed consolidation holds them."""
        return self.state is not ConsolidationStateEnum.DISMISSED

    def _move(self, state: ConsolidationStateEnum, now: datetime) -> None:
        self.state = state
        self.version += 1
        self.updated_at = now

    def _closed(self) -> ConsolidationClosedError:
        return ConsolidationClosedError(
            f"Consolidation {self.id.value} is {self.state.value}; this decision is closed.",
            {"consolidation_id": self.id.value, "state": self.state.value},
            next_steps=["Run `noesis consolidation show` to see how it ended."],
        )
