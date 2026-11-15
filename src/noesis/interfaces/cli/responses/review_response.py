"""`noesis review` output."""

from noesis.bounded_context.knowledge.application.dtos import (
    AcceptResultDto,
    BulkAcceptResultDto,
    EffectDto,
    RepairResultDto,
    RetractResultDto,
    ReviewDecisionDto,
    ReviewQueueItemDto,
    ReviewQueuePageDto,
)
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse
from .record_response import RecordActorResponse


class ReviewEffectResponse(FrozenObject):
    """What a supersession effect did.

    Attributes:
        record_id: The superseded record.
        outcome: `applied` or `skipped`.
        reason: Why it was skipped.
    """

    record_id: str
    outcome: str
    reason: str | None = None

    @classmethod
    def from_dto(cls, dto: EffectDto) -> ReviewEffectResponse:
        """The response item for an effect."""
        return cls(record_id=dto.record_id, outcome=dto.outcome, reason=dto.reason)


class ReviewAcceptResponse(IRenderableResponse):
    """`noesis review accept <id>`: the decision, or what it would be without `--yes`.

    Attributes:
        id: Record id.
        type: `knowledge` or `assertion`.
        status: Status after the decision.
        pinned_revision: Head judged (knowledge), else None.
        decision_seq: Sequence of the decision.
        basis: Basis of the decision.
        effects: Supersession effects the accept ran.
        conflicts: Always empty.
        applied: False for a preview.
        replayed: True when the key was already used and nothing was written.
    """

    id: str
    type: str
    status: str
    pinned_revision: int | None = None
    decision_seq: int
    basis: str
    effects: tuple[ReviewEffectResponse, ...] = ()
    conflicts: tuple[str, ...] = ()
    applied: bool
    replayed: bool = False

    @classmethod
    def from_dto(cls, dto: AcceptResultDto) -> ReviewAcceptResponse:
        """The response for a handler result."""
        return cls(
            id=dto.id,
            type=dto.type,
            status=dto.status,
            pinned_revision=dto.pinned_revision,
            decision_seq=dto.decision_seq,
            basis=dto.basis,
            effects=tuple(ReviewEffectResponse.from_dto(effect) for effect in dto.effects),
            conflicts=dto.conflicts,
            applied=dto.applied,
            replayed=dto.replayed,
        )

    def render(self) -> str:
        verb: str = "accepted" if self.applied else "would accept"
        note: str = " (replayed: nothing written)" if self.replayed else ""
        lines: list[str] = [f"{verb} {self.type} {self.id} ({self.basis}){note}"]
        lines += [
            f"supersession of {effect.record_id}: {effect.outcome}"
            + (f" ({effect.reason})" if effect.reason else "")
            for effect in self.effects
        ]
        if not self.applied:
            lines.append("preview only: pass --yes to apply")
        return "\n".join(lines)


class ReviewSampleResponse(FrozenObject):
    """A proposed knowledge record selected by tag.

    Attributes:
        id: Record id.
        title: Head title.
        subtype: Knowledge subtype.
        project_key: Project key, or None when space-wide.
        head_revision: Head revision number.
    """

    id: str
    title: str
    subtype: str
    project_key: str | None = None
    head_revision: int


class ReviewBulkAcceptResponse(IRenderableResponse):
    """`noesis review accept --tag T --all`: the counts and a sample.

    Attributes:
        tag: The tag.
        space: Space key.
        matched: Knowledge carrying the tag, any status.
        proposed: Of those, stored `proposed`.
        skipped_not_proposed: `matched - proposed`.
        accepted: Records accepted by this run (0 in a preview).
        skipped_changed: Records that changed before their turn (0 in a preview).
        basis: `migration`.
        sample: Up to 10 records, ascending id.
        applied: False for a preview.
    """

    tag: str
    space: str
    matched: int
    proposed: int
    skipped_not_proposed: int
    accepted: int
    skipped_changed: int
    basis: str
    sample: tuple[ReviewSampleResponse, ...] = ()
    applied: bool

    @classmethod
    def from_dto(cls, dto: BulkAcceptResultDto) -> ReviewBulkAcceptResponse:
        """The response for a handler result."""
        return cls(
            tag=dto.tag,
            space=dto.space,
            matched=dto.matched,
            proposed=dto.proposed,
            skipped_not_proposed=dto.skipped_not_proposed,
            accepted=dto.accepted,
            skipped_changed=dto.skipped_changed,
            basis=dto.basis,
            sample=tuple(
                ReviewSampleResponse(
                    id=item.id,
                    title=item.title,
                    subtype=item.subtype,
                    project_key=item.project_key,
                    head_revision=item.head_revision,
                )
                for item in dto.sample
            ),
            applied=dto.applied,
        )

    def render(self) -> str:
        head: str = (
            f"accepted {self.accepted} of {self.proposed} proposed"
            if self.applied
            else f"would accept {self.proposed} proposed"
        )
        lines: list[str] = [
            f"{head} (tag {self.tag}, {self.matched} matched, "
            f"{self.skipped_not_proposed} not proposed, {self.skipped_changed} changed)"
        ]
        lines += [f"  {item.id} {item.title}" for item in self.sample]
        if not self.applied:
            lines.append("preview only: the user applies it with --yes in a terminal")
        return "\n".join(lines)


class ReviewRetractResponse(IRenderableResponse):
    """`noesis review retract <id>`: the decision, or what it would be without `--yes`.

    Attributes:
        id: Record id.
        status: `retracted`.
        outcome: `rejected` (from proposed) or `retracted` (from accepted).
        applied: False for a preview.
        replayed: True when the key was already used and nothing was written.
    """

    id: str
    status: str
    outcome: str
    applied: bool
    replayed: bool = False

    @classmethod
    def from_dto(cls, dto: RetractResultDto) -> ReviewRetractResponse:
        """The response for a handler result."""
        return cls(
            id=dto.id,
            status=dto.status,
            outcome=dto.outcome,
            applied=dto.applied,
            replayed=dto.replayed,
        )

    def render(self) -> str:
        verb: str = self.outcome if self.applied else f"would be {self.outcome}"
        note: str = " (replayed: nothing written)" if self.replayed else ""
        suffix: str = "" if self.applied else " (preview only: pass --yes to apply)"
        return f"{self.id} {verb}{note}{suffix}"


class ReviewDecisionResponse(FrozenObject):
    """One decision of a record's history.

    Attributes:
        seq: 1..n per record.
        transition: `accept`, `reject`, `retract` or `supersede`.
        from_status: Status before.
        to_status: Status after.
        actor: Who decided.
        decided_at: ISO 8601 time.
        reason: Why, when given.
        basis: Basis of the decision.
        pinned_revision: Head judged (accept of knowledge).
        cause_assertion_id: Causing assertion (supersede).
    """

    seq: int
    transition: str
    from_status: str
    to_status: str
    actor: RecordActorResponse
    decided_at: str
    reason: str | None = None
    basis: str
    pinned_revision: int | None = None
    cause_assertion_id: str | None = None

    @classmethod
    def from_dto(cls, dto: ReviewDecisionDto) -> ReviewDecisionResponse:
        """The response item for a decision."""
        return cls(
            seq=dto.seq,
            transition=dto.transition,
            from_status=dto.from_status,
            to_status=dto.to_status,
            actor=RecordActorResponse(
                kind=dto.actor_kind, name=dto.actor_name, session=dto.actor_session
            ),
            decided_at=dto.decided_at,
            reason=dto.reason,
            basis=dto.basis,
            pinned_revision=dto.pinned_revision,
            cause_assertion_id=dto.cause_assertion_id,
        )


class ReviewLogResponse(IRenderableResponse):
    """`noesis review log <id>`: the decisions of one record, ordered by `seq`.

    Attributes:
        decisions: The decisions.
    """

    decisions: tuple[ReviewDecisionResponse, ...] = ()

    @classmethod
    def from_dtos(cls, dtos: list[ReviewDecisionDto]) -> ReviewLogResponse:
        """The response for a handler result."""
        return cls(decisions=tuple(ReviewDecisionResponse.from_dto(dto) for dto in dtos))

    def render(self) -> str:
        if not self.decisions:
            return "no decisions"
        return "\n".join(
            f"{item.seq}. {item.transition} {item.from_status} -> {item.to_status} "
            f"by {item.actor.kind} {item.actor.name} ({item.basis}) at {item.decided_at}"
            + (f": {item.reason}" if item.reason else "")
            for item in self.decisions
        )


class ReviewRepairEffectResponse(FrozenObject):
    """What `review repair` did for one pending effect.

    Attributes:
        assertion_id: The accepted `supersedes` assertion.
        record_id: The record it supersedes.
        outcome: `applied` or `skipped`; a preview shows what would be applied.
        reason: Why it was skipped.
    """

    assertion_id: str | None = None
    record_id: str
    outcome: str
    reason: str | None = None


class ReviewRepairResponse(IRenderableResponse):
    """`noesis review repair`: the pending supersession effects and what became of them.

    Attributes:
        effects: One entry per pending effect.
        applied: False for a preview.
    """

    effects: tuple[ReviewRepairEffectResponse, ...] = ()
    applied: bool

    @classmethod
    def from_dto(cls, dto: RepairResultDto) -> ReviewRepairResponse:
        """The response for a handler result."""
        return cls(
            effects=tuple(
                ReviewRepairEffectResponse(
                    assertion_id=effect.assertion_id,
                    record_id=effect.record_id,
                    outcome=effect.outcome,
                    reason=effect.reason,
                )
                for effect in dto.effects
            ),
            applied=dto.applied,
        )

    def render(self) -> str:
        if not self.effects:
            return "no pending supersession effects"
        lines: list[str] = [
            f"{effect.record_id} (by {effect.assertion_id}): {effect.outcome}"
            + (f" ({effect.reason})" if effect.reason else "")
            for effect in self.effects
        ]
        if not self.applied:
            lines.append("preview only: pass --yes to apply")
        return "\n".join(lines)


class ReviewQueueApplicabilityResponse(FrozenObject):
    """Where a queued record applies.

    Attributes:
        project_key: Project key; None means space-wide.
        tags: Tags.
    """

    project_key: str | None = None
    tags: tuple[str, ...] = ()


class ReviewQueueItemResponse(FrozenObject):
    """One proposed record waiting for a decision.

    Attributes:
        id: Record id.
        type: `knowledge` or `assertion`.
        title: Head title (knowledge).
        predicate: Predicate (assertion).
        subject_id: Subject (assertion).
        object_id: Object (assertion).
        applicability: Project key and tags.
        requires: `user` or `agent_or_user`.
        decidable_by_caller: Whether the calling actor may decide it.
        evidence_count: Evidence records (assertion); None for knowledge.
        consolidation_id: Consolidation that produced it, or None.
    """

    id: str
    type: str
    title: str | None = None
    predicate: str | None = None
    subject_id: str | None = None
    object_id: str | None = None
    applicability: ReviewQueueApplicabilityResponse
    requires: str | None = None
    decidable_by_caller: bool | None = None
    evidence_count: int | None = None
    consolidation_id: str | None = None

    @classmethod
    def from_dto(cls, dto: ReviewQueueItemDto) -> ReviewQueueItemResponse:
        """The response item for a queue item."""
        return cls(
            id=dto.id,
            type=dto.type,
            title=dto.title,
            predicate=dto.predicate,
            subject_id=dto.subject_id,
            object_id=dto.object_id,
            applicability=ReviewQueueApplicabilityResponse(
                project_key=dto.project_key, tags=dto.tags
            ),
            requires=dto.requires,
            decidable_by_caller=dto.decidable_by_caller,
            evidence_count=dto.evidence_count,
            consolidation_id=dto.consolidation_id,
        )


class ReviewQueueResponse(IRenderableResponse):
    """`noesis review queue`: one page of proposed records, ascending id.

    Attributes:
        items: The page.
        next_cursor: Pass it as `--cursor` for the next page; None on the last page.
    """

    items: tuple[ReviewQueueItemResponse, ...] = ()
    next_cursor: str | None = None

    @classmethod
    def from_dto(cls, dto: ReviewQueuePageDto) -> ReviewQueueResponse:
        """The response for a handler result."""
        return cls(
            items=tuple(ReviewQueueItemResponse.from_dto(item) for item in dto.items),
            next_cursor=dto.next_cursor,
        )

    def render(self) -> str:
        if not self.items:
            return "nothing to review"
        lines: list[str] = []
        for item in self.items:
            what: str = item.title or f"{item.subject_id} {item.predicate} {item.object_id}"
            who: str = "you may decide" if item.decidable_by_caller else f"needs {item.requires}"
            lines.append(f"{item.id} {item.type}: {what} ({who})")
        if self.next_cursor:
            lines.append(f"next: --cursor {self.next_cursor}")
        return "\n".join(lines)
