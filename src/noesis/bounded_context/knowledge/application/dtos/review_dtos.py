"""DTOs of the review module: queue, states, assertions, decisions and command results."""

from noesis.shared_kernel.application.dtos import BaseDto


class ReviewQueueItemDto(BaseDto):
    """One proposed record waiting for a decision.

    Attributes:
        id: Record id.
        type: `knowledge` or `assertion`.
        title: Head title (Knowledge); None for an assertion.
        predicate: Predicate (assertion); None for Knowledge.
        subject_id: Subject (assertion).
        object_id: Object (assertion).
        project_id: Applicability project id, or None when space-wide.
        project_key: Applicability project key, or None when space-wide.
        tags: Applicability tags.
        evidence_count: Evidence records (assertion); None for Knowledge.
        consolidation_id: Consolidation that produced it, or None.
        requires: `user` or `agent_or_user`; filled by the handler.
        decidable_by_caller: Whether the calling actor may decide it; filled by the handler.
    """

    id: str
    type: str
    title: str | None = None
    predicate: str | None = None
    subject_id: str | None = None
    object_id: str | None = None
    project_id: str | None = None
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    evidence_count: int | None = None
    consolidation_id: str | None = None
    requires: str | None = None
    decidable_by_caller: bool | None = None


class ReviewQueuePageDto(BaseDto):
    """A page of the review queue.

    Attributes:
        items: Items in ascending record id.
        next_cursor: Pass it back for the next page; None on the last page.
    """

    items: tuple[ReviewQueueItemDto, ...] = ()
    next_cursor: str | None = None


class TagMatchCountsDto(BaseDto):
    """How many Knowledge records carry a tag.

    Attributes:
        matched: Records carrying the tag, any status.
        proposed: Of those, the ones stored `proposed`.
    """

    matched: int
    proposed: int


class TaggedProposalDto(BaseDto):
    """A proposed Knowledge record selected by tag.

    Attributes:
        id: Record id.
        title: Title of the head revision.
        subtype: Knowledge subtype.
        project_key: Project key, or None when space-wide.
        head_revision: Head revision number.
    """

    id: str
    title: str
    subtype: str
    project_key: str | None = None
    head_revision: int


class AssertionDto(BaseDto):
    """An assertion with the review state of its endpoints.

    Attributes:
        id: Assertion id.
        space_id: Space.
        predicate: Predicate.
        subject_id: Subject id.
        subject_at_revision: Subject revision judged.
        subject_effective_status: Effective status of the subject; None without status.
        object_id: Object id.
        object_at_revision: Object revision judged.
        object_effective_status: Effective status of the object; None without status.
        evidence_ids: Evidence ids.
        rationale: Why.
        project_key: Project key, or None when space-wide.
        tags: Tags.
        status: Stored status.
        effective_status: Derived status.
        superseded_by_assertion_id: Accepted `supersedes` assertion targeting it, or None.
        superseded_by_record_id: Subject of that assertion, or None.
        actor_kind: Who asserted it.
        actor_name: Actor name.
        actor_session: Actor session.
        source_ids: Sources.
        created_at: ISO 8601 creation time.
    """

    id: str
    space_id: str
    predicate: str
    subject_id: str
    subject_at_revision: int | None = None
    subject_effective_status: str | None = None
    object_id: str
    object_at_revision: int | None = None
    object_effective_status: str | None = None
    evidence_ids: tuple[str, ...] = ()
    rationale: str
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    status: str
    effective_status: str
    superseded_by_assertion_id: str | None = None
    superseded_by_record_id: str | None = None
    actor_kind: str
    actor_name: str
    actor_session: str | None = None
    source_ids: tuple[str, ...] = ()
    created_at: str


class AssertionSummaryDto(BaseDto):
    """Published summary of an assertion; one to one with `AssertionSummaryContract`.

    Attributes:
        assertion_id: Assertion id.
        predicate: Predicate.
        subject_id: Subject id.
        subject_at_revision: Subject revision judged.
        object_id: Object id.
        object_at_revision: Object revision judged.
        object_type: Record type of the object.
        status: Stored status.
        evidence_ids: Evidence ids.
        project_key: Applicability project key.
        tags: Applicability tags.
        decision_basis: Basis of the latest review decision; None while undecided.
    """

    assertion_id: str
    predicate: str
    subject_id: str
    subject_at_revision: int | None = None
    object_id: str
    object_at_revision: int | None = None
    object_type: str
    status: str
    evidence_ids: tuple[str, ...] = ()
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    decision_basis: str | None = None


class ReviewDecisionDto(BaseDto):
    """One decision of a record's history.

    Attributes:
        seq: 1..n per record.
        transition: `accept`, `reject`, `retract` or `supersede`.
        from_status: Status before.
        to_status: Status after.
        actor_kind: `user` or `agent`.
        actor_name: Actor name.
        actor_session: Actor session.
        decided_at: ISO 8601 time.
        reason: Why, when given.
        basis: Basis of the decision.
        pinned_revision: Head judged (accept of Knowledge).
        cause_assertion_id: Causing assertion (supersede).
    """

    seq: int
    transition: str
    from_status: str
    to_status: str
    actor_kind: str
    actor_name: str
    actor_session: str | None = None
    decided_at: str
    reason: str | None = None
    basis: str
    pinned_revision: int | None = None
    cause_assertion_id: str | None = None


class ReviewStateDto(BaseDto):
    """Review state of a record; one to one with `RecordReviewStateContract`.

    Attributes:
        record_id: Record id.
        record_type: Record type.
        status: Stored status; None without status.
        effective_status: Derived status; None without status.
        authority: Authority label.
        head_revision: Head revision for types with revisions.
        superseded_by_assertion_id: Accepted `supersedes` assertion targeting it.
        superseded_by_record_ids: Subjects of those assertions.
        project_key: Applicability project key.
        tags: Applicability tags.
        decided_by_kind: Actor kind of the latest decision.
        decided_at: ISO 8601 time of the latest decision.
    """

    record_id: str
    record_type: str
    status: str | None = None
    effective_status: str | None = None
    authority: str
    head_revision: int | None = None
    superseded_by_assertion_id: str | None = None
    superseded_by_record_ids: tuple[str, ...] = ()
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    decided_by_kind: str | None = None
    decided_at: str | None = None


class PendingEffectDto(BaseDto):
    """An accepted `supersedes` assertion whose object is still stored `accepted`.

    Attributes:
        assertion_id: The assertion.
        object_id: Its object.
    """

    assertion_id: str
    object_id: str


class EffectDto(BaseDto):
    """Outcome of applying a supersession effect.

    Attributes:
        record_id: The superseded record.
        outcome: `applied` or `skipped`.
        reason: Why it was skipped.
        assertion_id: The `supersedes` assertion.
    """

    record_id: str
    outcome: str
    reason: str | None = None
    assertion_id: str | None = None


class ProposeAssertionResultDto(BaseDto):
    """The proposed assertion.

    Attributes:
        id: Assertion id.
        predicate: Predicate.
        subject_id: Subject id.
        subject_at_revision: Subject revision judged.
        object_id: Object id.
        object_at_revision: Object revision judged.
        evidence_ids: Evidence ids.
        project_key: Project key, or None when space-wide.
        tags: Tags.
        status: `proposed`.
        space_id: Space.
        replayed: True when the key was already used and nothing was written.
    """

    id: str
    predicate: str
    subject_id: str
    subject_at_revision: int | None = None
    object_id: str
    object_at_revision: int | None = None
    evidence_ids: tuple[str, ...] = ()
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    status: str
    space_id: str
    replayed: bool = False


class AcceptResultDto(BaseDto):
    """Result of accepting a record.

    Attributes:
        id: Record id.
        type: `knowledge` or `assertion`.
        status: Status after the decision.
        pinned_revision: Head judged (Knowledge), else None.
        decision_seq: Sequence of the decision.
        basis: Basis of the decision.
        effects: Supersession effects run by the accept.
        conflicts: Always empty (default, not yet confirmed).
        applied: False for a preview.
        space_id: Space.
        replayed: True when the key was already used.
    """

    id: str
    type: str
    status: str
    pinned_revision: int | None = None
    decision_seq: int
    basis: str
    effects: tuple[EffectDto, ...] = ()
    conflicts: tuple[str, ...] = ()
    applied: bool
    space_id: str
    replayed: bool = False


class RetractResultDto(BaseDto):
    """Result of rejecting or retracting a record.

    Attributes:
        id: Record id.
        status: `retracted`.
        outcome: `rejected` (from proposed) or `retracted` (from accepted).
        applied: False for a preview.
        decision_seq: Sequence of the decision.
        space_id: Space.
        replayed: True when the key was already used.
    """

    id: str
    status: str
    outcome: str
    applied: bool
    decision_seq: int
    space_id: str
    replayed: bool = False


class BulkAcceptResultDto(BaseDto):
    """Result of the bulk accept by tag.

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
    sample: tuple[TaggedProposalDto, ...] = ()
    applied: bool


class RepairResultDto(BaseDto):
    """Result of `review repair`.

    Attributes:
        effects: One entry per pending effect found.
        applied: False for a preview.
    """

    effects: tuple[EffectDto, ...] = ()
    applied: bool
