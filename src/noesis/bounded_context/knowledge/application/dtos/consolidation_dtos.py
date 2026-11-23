"""DTOs of the consolidation module: read models, scan results and command results."""

from noesis.bounded_context.knowledge.domain.value_objects import DismissalReasonKindEnum
from noesis.shared_kernel.application.dtos import BaseDto

LINK_POLICY: str = "preserve_originals"
"""Every original LinkSet and edge stays as imported; the successor inherits none."""


class ConsolidationMemberDto(BaseDto):
    """One original of a consolidation.

    Attributes:
        record_id: The Knowledge record.
        at_revision: The accepted head revision that was judged.
        title: Current head title, when known.
        effective_status: Current derived status, when known.
    """

    record_id: str
    at_revision: int
    title: str | None = None
    effective_status: str | None = None


class ConsolidationDismissalDto(BaseDto):
    """Why a consolidation was dismissed.

    Attributes:
        reason_kind: `distinct`, `poor_draft` or `other`.
        reason: The explanation.
        actor_kind: `user` or `agent`.
        actor_name: Who.
        dismissed_at: ISO 8601 time.
    """

    reason_kind: DismissalReasonKindEnum
    reason: str
    actor_kind: str
    actor_name: str
    dismissed_at: str


class ConsolidationDto(BaseDto):
    """A consolidation as stored.

    Attributes:
        id: Consolidation id.
        space_id: Space.
        kind: `graph_merge`.
        state: `opened`, `materialised`, `acceptance_started` or `dismissed`.
        fingerprint: Hash of the member pairs.
        rationale: Why.
        project_key: Members' project key; None when space-wide.
        successor_id: The proposed successor, once materialised.
        produced_assertion_ids: The proposed `supersedes` assertions.
        version: Concurrency token.
        created_by_kind: Who opened it.
        created_by_name: Their name.
        created_at: ISO 8601 time.
        members: The originals, ascending record id.
        dismissal: Why it was dismissed, when it was.
    """

    id: str
    space_id: str
    kind: str
    state: str
    fingerprint: str
    rationale: str
    project_key: str | None = None
    successor_id: str | None = None
    produced_assertion_ids: tuple[str, ...] = ()
    version: int
    created_by_kind: str
    created_by_name: str
    created_at: str
    members: tuple[ConsolidationMemberDto, ...] = ()
    dismissal: ConsolidationDismissalDto | None = None


class ConsolidationPageDto(BaseDto):
    """A page of consolidations.

    Attributes:
        items: Consolidations in ascending id.
        next_cursor: Pass it back for the next page; None on the last page.
    """

    items: tuple[ConsolidationDto, ...] = ()
    next_cursor: str | None = None


class ProducedRecordDto(BaseDto):
    """A record a consolidation produced, with its current review state.

    Attributes:
        record_id: The record.
        record_type: `knowledge` or `assertion`.
        status: Stored status.
        effective_status: Derived status.
    """

    record_id: str
    record_type: str
    status: str | None = None
    effective_status: str | None = None


class ConsolidationDetailDto(BaseDto):
    """`consolidation show`.

    Attributes:
        consolidation: The aggregate.
        progress: `pending`, `partially_applied`, `applied` or `successor_retracted`.
        produced: The successor and its assertions with current states.
        link_policy: Always `preserve_originals`.
        requires: `user` or `agent_or_user`.
        decidable_by_caller: Whether the calling actor may decide it.
        membership_note: Why the members stay reserved, when they do.
    """

    consolidation: ConsolidationDto
    progress: str
    produced: tuple[ProducedRecordDto, ...] = ()
    link_policy: str = LINK_POLICY
    requires: str
    decidable_by_caller: bool
    membership_note: str | None = None


class CandidateSnapshotDto(BaseDto):
    """A Knowledge record as the scan and the guards read it.

    Attributes:
        record_id: The record.
        record_type: Its type.
        subtype: Knowledge subtype.
        project_id: Project id; None when space-wide.
        project_key: Project key; None when space-wide.
        tags: Tags.
        stored_status: Stored status.
        effective_status: Derived status.
        head_revision: Head revision.
        title: Head title.
        accepted_at: ISO 8601 time of the latest accept decision, when any.
    """

    record_id: str
    record_type: str
    subtype: str | None = None
    project_id: str | None = None
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    stored_status: str | None = None
    effective_status: str | None = None
    head_revision: int | None = None
    title: str | None = None
    accepted_at: str | None = None


class CandidateSnapshotPageDto(BaseDto):
    """A page of accepted Knowledge, latest accepted first.

    Attributes:
        items: Snapshots ordered by latest accept time descending, then id.
        next_cursor: Pass it back for the next page; None on the last page.
    """

    items: tuple[CandidateSnapshotDto, ...] = ()
    next_cursor: str | None = None


class OpenMembershipDto(BaseDto):
    """A record held by an open consolidation.

    Attributes:
        record_id: The record.
        consolidation_id: The consolidation that holds it.
    """

    record_id: str
    consolidation_id: str


class ScanCandidateDto(BaseDto):
    """A record that may overlap the anchor.

    Attributes:
        record_id: The record.
        title: Head title.
        revision: Head revision.
        rank: Position in the similarity order (not a score).
        found_by: `lexical`, `graph`, `semantic`.
        dismissed_in: The dismissal that judged the pair distinct, when `--include-dismissed`.
    """

    record_id: str
    title: str | None = None
    revision: int | None = None
    rank: int
    found_by: tuple[str, ...] = ()
    dismissed_in: str | None = None


class ScanGroupDto(BaseDto):
    """An anchor and the records that may overlap it.

    Attributes:
        anchor_id: The anchor.
        anchor_title: Its title.
        anchor_revision: Its head revision.
        candidates: Eligible overlapping records.
        conflicts: Overlapping records that an open consolidation already holds.
        requires: Who must decide a consolidation of this group.
    """

    anchor_id: str
    anchor_title: str | None = None
    anchor_revision: int | None = None
    candidates: tuple[ScanCandidateDto, ...] = ()
    conflicts: tuple[OpenMembershipDto, ...] = ()
    requires: str


class ConsolidationScanDto(BaseDto):
    """`consolidation scan`; it writes nothing.

    Attributes:
        groups: Anchors with at least one candidate.
        semantic_state: Worst state seen: unavailable, absent, lagging, ready.
        suppressed_count: Pairs hidden by a `distinct` dismissal.
        excluded_unaccepted_migrated: Proposed migrated records left out.
        next_cursor: Pass it back for the next anchors.
        next_steps: What the user may do next.
    """

    groups: tuple[ScanGroupDto, ...] = ()
    semantic_state: str
    suppressed_count: int = 0
    excluded_unaccepted_migrated: int = 0
    next_cursor: str | None = None
    next_steps: tuple[str, ...] = ()


class ConsolidationStepDto(BaseDto):
    """One effect of a consolidation command.

    Attributes:
        target: The record or assertion, or a named step.
        target_type: `knowledge`, `assertion` or `consolidation`.
        outcome: `planned`, `not_authorised`, `accepted`, `already_accepted`, `rejected`,
            `already_retracted`, `left_accepted`, `done`, `failed` or `not_run`.
        error_code: The typed error of a failed or refused step.
    """

    target: str
    target_type: str
    outcome: str
    error_code: str | None = None


class PlannedAssertionDto(BaseDto):
    """An assertion a dry run would propose.

    Attributes:
        object_id: The original it would supersede.
        evidence_ids: Independent evidence it would carry.
    """

    object_id: str
    evidence_ids: tuple[str, ...] = ()


class ConsolidationProposalDto(BaseDto):
    """`consolidation propose`.

    Attributes:
        consolidation_id: The reserved id; None for a dry run.
        kind: `graph_merge`.
        state: Aggregate state; `planned` for a dry run.
        members: The originals with the revisions judged.
        successor_id: The proposed successor; None for a dry run.
        successor_status: Its current status.
        assertions: The proposed assertions with current status.
        planned_assertions: What a dry run would propose.
        requires: Who must decide.
        decidable_by_caller: Whether the calling actor may decide.
        dry_run: Whether nothing was written.
        link_policy: Always `preserve_originals`.
        progress: Derived review progress.
        replayed: True when the key was already used and nothing new was written.
        next_steps: What to run next.
    """

    consolidation_id: str | None = None
    kind: str
    state: str
    members: tuple[ConsolidationMemberDto, ...]
    successor_id: str | None = None
    successor_status: str | None = None
    assertions: tuple[ProducedRecordDto, ...] = ()
    planned_assertions: tuple[PlannedAssertionDto, ...] = ()
    requires: str
    decidable_by_caller: bool
    dry_run: bool
    link_policy: str = LINK_POLICY
    progress: str
    replayed: bool = False
    next_steps: tuple[str, ...] = ()


class ConsolidationDecisionDto(BaseDto):
    """`consolidation accept` and `consolidation reject`.

    Attributes:
        consolidation_id: The consolidation.
        state: Aggregate state after the command.
        preview: True when nothing was written.
        steps: One entry per effect.
        progress: Derived review progress.
        replayed: True when the key was already completed.
    """

    consolidation_id: str
    state: str
    preview: bool
    steps: tuple[ConsolidationStepDto, ...] = ()
    progress: str
    replayed: bool = False
