"""`noesis consolidation` output."""

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDecisionDto,
    ConsolidationDetailDto,
    ConsolidationDto,
    ConsolidationPageDto,
    ConsolidationProposalDto,
    ConsolidationScanDto,
    ConsolidationStepDto,
    ProducedRecordDto,
)
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class ConsolidationMemberResponse(FrozenObject):
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


class ConsolidationProducedResponse(FrozenObject):
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

    @classmethod
    def from_dto(cls, dto: ProducedRecordDto) -> ConsolidationProducedResponse:
        """The response item for a produced record."""
        return cls.model_validate(dto, from_attributes=True)


class ConsolidationStepResponse(FrozenObject):
    """One effect of an accept or reject.

    Attributes:
        target: The record or consolidation.
        target_type: `knowledge`, `assertion` or `consolidation`.
        outcome: What happened or would happen.
        error_code: The typed error of a failed or refused step.
    """

    target: str
    target_type: str
    outcome: str
    error_code: str | None = None

    @classmethod
    def from_dto(cls, dto: ConsolidationStepDto) -> ConsolidationStepResponse:
        """The response item for a step."""
        return cls.model_validate(dto, from_attributes=True)


class ConsolidationDismissalResponse(FrozenObject):
    """Why a consolidation was dismissed.

    Attributes:
        reason_kind: `distinct`, `poor_draft` or `other`.
        reason: The explanation.
        actor_kind: `user` or `agent`.
        actor_name: Who.
        dismissed_at: ISO 8601 time.
    """

    reason_kind: str
    reason: str
    actor_kind: str
    actor_name: str
    dismissed_at: str


class ConsolidationItemResponse(FrozenObject):
    """A consolidation as stored.

    Attributes:
        id: Consolidation id.
        kind: `graph_merge`.
        state: `opened`, `materialised`, `acceptance_started` or `dismissed`.
        rationale: Why.
        project_key: Members' project, or None when space-wide.
        successor_id: The proposed successor, once materialised.
        produced_assertion_ids: The proposed `supersedes` assertions.
        created_by: Who opened it, as `kind:name`.
        created_at: ISO 8601 time.
        members: The originals.
        dismissal: Why it was dismissed, when it was.
    """

    id: str
    kind: str
    state: str
    rationale: str
    project_key: str | None = None
    successor_id: str | None = None
    produced_assertion_ids: tuple[str, ...] = ()
    created_by: str
    created_at: str
    members: tuple[ConsolidationMemberResponse, ...] = ()
    dismissal: ConsolidationDismissalResponse | None = None

    @classmethod
    def from_dto(cls, dto: ConsolidationDto) -> ConsolidationItemResponse:
        """The response item for a stored consolidation."""
        return cls(
            id=dto.id,
            kind=dto.kind,
            state=dto.state,
            rationale=dto.rationale,
            project_key=dto.project_key,
            successor_id=dto.successor_id,
            produced_assertion_ids=dto.produced_assertion_ids,
            created_by=f"{dto.created_by_kind}:{dto.created_by_name}",
            created_at=dto.created_at,
            members=tuple(
                ConsolidationMemberResponse.model_validate(m, from_attributes=True)
                for m in dto.members
            ),
            dismissal=(
                ConsolidationDismissalResponse.model_validate(dto.dismissal, from_attributes=True)
                if dto.dismissal
                else None
            ),
        )

    def line(self) -> str:
        """One text line."""
        scope: str = self.project_key or "space-wide"
        return f"{self.id}  {self.state}  {scope}  {len(self.members)} members"


class ScanCandidateResponse(FrozenObject):
    """A record that may overlap the anchor.

    Attributes:
        record_id: The record.
        title: Head title.
        revision: Head revision.
        rank: Position in the similarity order (not a score).
        found_by: `lexical`, `graph`, `semantic`.
        dismissed_in: The dismissal that judged the pair distinct.
    """

    record_id: str
    title: str | None = None
    revision: int | None = None
    rank: int
    found_by: tuple[str, ...] = ()
    dismissed_in: str | None = None


class ScanConflictResponse(FrozenObject):
    """A record an open consolidation already holds.

    Attributes:
        record_id: The record.
        consolidation_id: The consolidation that holds it.
    """

    record_id: str
    consolidation_id: str


class ScanGroupResponse(FrozenObject):
    """An anchor and the records that may overlap it.

    Attributes:
        anchor_id: The anchor.
        anchor_title: Its title.
        anchor_revision: Its head revision.
        candidates: Eligible overlapping records.
        conflicts: Overlapping records an open consolidation holds.
        requires: Who must decide a consolidation of this group.
    """

    anchor_id: str
    anchor_title: str | None = None
    anchor_revision: int | None = None
    candidates: tuple[ScanCandidateResponse, ...] = ()
    conflicts: tuple[ScanConflictResponse, ...] = ()
    requires: str


class ConsolidationScanResponse(IRenderableResponse):
    """`noesis consolidation scan`: ranked candidates, never scores; nothing is written.

    Attributes:
        groups: Anchors with at least one candidate.
        semantic_state: Worst state seen: unavailable, absent, lagging, ready.
        suppressed_count: Pairs hidden by a `distinct` dismissal.
        excluded_unaccepted_migrated: Proposed migrated records left out.
        next_cursor: Pass it back for the next anchors.
        next_steps: What the user may do next.
    """

    groups: tuple[ScanGroupResponse, ...] = ()
    semantic_state: str
    suppressed_count: int = 0
    excluded_unaccepted_migrated: int = 0
    next_cursor: str | None = None
    next_steps: tuple[str, ...] = ()

    @classmethod
    def from_dto(cls, dto: ConsolidationScanDto) -> ConsolidationScanResponse:
        """The response for a handler result."""
        return cls.model_validate(dto, from_attributes=True)

    def render(self) -> str:
        lines: list[str] = []
        for group in self.groups:
            lines.append(
                f"anchor {group.anchor_id}  {group.anchor_title or ''}  [{group.requires}]"
            )
            for candidate in group.candidates:
                dismissed: str = (
                    f"  (dismissed in {candidate.dismissed_in})" if candidate.dismissed_in else ""
                )
                lines.append(
                    f"  #{candidate.rank} {candidate.record_id}  {candidate.title or ''}  "
                    f"[{', '.join(candidate.found_by)}]{dismissed}"
                )
            lines += [f"  held by {c.consolidation_id}: {c.record_id}" for c in group.conflicts]
        if not self.groups:
            lines.append("no overlapping candidates")
        lines.append(
            f"semantic: {self.semantic_state}; suppressed: {self.suppressed_count}; "
            f"unreviewed migrated: {self.excluded_unaccepted_migrated}"
        )
        if self.next_cursor:
            lines.append(f"next: --cursor {self.next_cursor}")
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)


class PlannedAssertionResponse(FrozenObject):
    """An assertion a dry run would propose.

    Attributes:
        object_id: The original it would supersede.
        evidence_ids: Independent evidence it would carry.
    """

    object_id: str
    evidence_ids: tuple[str, ...] = ()


class ConsolidationProposeResponse(IRenderableResponse):
    """`noesis consolidation propose`: the reserved consolidation and its proposals.

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
    members: tuple[ConsolidationMemberResponse, ...]
    successor_id: str | None = None
    successor_status: str | None = None
    assertions: tuple[ConsolidationProducedResponse, ...] = ()
    planned_assertions: tuple[PlannedAssertionResponse, ...] = ()
    requires: str
    decidable_by_caller: bool
    dry_run: bool
    link_policy: str
    progress: str
    replayed: bool = False
    next_steps: tuple[str, ...] = ()

    @classmethod
    def from_dto(cls, dto: ConsolidationProposalDto) -> ConsolidationProposeResponse:
        """The response for a handler result."""
        return cls(
            consolidation_id=dto.consolidation_id,
            kind=dto.kind,
            state=dto.state,
            members=tuple(
                ConsolidationMemberResponse.model_validate(m, from_attributes=True)
                for m in dto.members
            ),
            successor_id=dto.successor_id,
            successor_status=dto.successor_status,
            assertions=tuple(ConsolidationProducedResponse.from_dto(a) for a in dto.assertions),
            planned_assertions=tuple(
                PlannedAssertionResponse.model_validate(p, from_attributes=True)
                for p in dto.planned_assertions
            ),
            requires=dto.requires,
            decidable_by_caller=dto.decidable_by_caller,
            dry_run=dto.dry_run,
            link_policy=dto.link_policy,
            progress=dto.progress,
            replayed=dto.replayed,
            next_steps=dto.next_steps,
        )

    def render(self) -> str:
        head: str = (
            "dry run: nothing written"
            if self.dry_run
            else f"consolidation {self.consolidation_id} {self.state}"
            + (" (replayed: nothing new written)" if self.replayed else "")
        )
        lines: list[str] = [head]
        lines += [f"original {m.record_id} @ revision {m.at_revision}" for m in self.members]
        if self.successor_id:
            lines.append(f"successor {self.successor_id} ({self.successor_status})")
        lines += [f"supersedes {a.record_id} ({a.status})" for a in self.assertions]
        lines += [
            f"would supersede {p.object_id} with {len(p.evidence_ids)} evidence record(s)"
            for p in self.planned_assertions
        ]
        lines.append(
            f"decided by: {self.requires}; originals, revisions and links stay as they are "
            f"({self.link_policy})"
        )
        lines += [f"next: {step}" for step in self.next_steps]
        return "\n".join(lines)


class ConsolidationShowResponse(IRenderableResponse):
    """`noesis consolidation show`: the aggregate, its progress and the produced records.

    Attributes:
        consolidation: The aggregate.
        progress: `pending`, `partially_applied`, `applied` or `successor_retracted`.
        produced: The successor and its assertions with current states.
        link_policy: Always `preserve_originals`.
        requires: `user` or `agent_or_user`.
        decidable_by_caller: Whether the calling actor may decide it.
        membership_note: Why the members stay reserved, when they do.
    """

    consolidation: ConsolidationItemResponse
    progress: str
    produced: tuple[ConsolidationProducedResponse, ...] = ()
    link_policy: str
    requires: str
    decidable_by_caller: bool
    membership_note: str | None = None

    @classmethod
    def from_dto(cls, dto: ConsolidationDetailDto) -> ConsolidationShowResponse:
        """The response for a handler result."""
        return cls(
            consolidation=ConsolidationItemResponse.from_dto(dto.consolidation),
            progress=dto.progress,
            produced=tuple(ConsolidationProducedResponse.from_dto(p) for p in dto.produced),
            link_policy=dto.link_policy,
            requires=dto.requires,
            decidable_by_caller=dto.decidable_by_caller,
            membership_note=dto.membership_note,
        )

    def render(self) -> str:
        item: ConsolidationItemResponse = self.consolidation
        lines: list[str] = [
            f"consolidation {item.id}: {item.state}, progress {self.progress}",
            f"why: {item.rationale}",
        ]
        lines += [
            f"original {m.record_id} @ revision {m.at_revision}"
            f"  {m.effective_status or '?'}  {m.title or ''}"
            for m in item.members
        ]
        lines += [
            f"{p.record_type} {p.record_id}: {p.effective_status or p.status}"
            for p in self.produced
        ]
        if item.dismissal:
            lines.append(
                f"dismissed ({item.dismissal.reason_kind}) by {item.dismissal.actor_name}: "
                f"{item.dismissal.reason}"
            )
        if self.membership_note:
            lines.append(self.membership_note)
        lines.append(
            f"decided by: {self.requires}; this caller may decide: {self.decidable_by_caller}; "
            f"links: {self.link_policy}"
        )
        return "\n".join(lines)


class ConsolidationListResponse(IRenderableResponse):
    """`noesis consolidation list`: a page of consolidations.

    Attributes:
        items: Consolidations in ascending id.
        next_cursor: Pass it back for the next page; None on the last page.
    """

    items: tuple[ConsolidationItemResponse, ...] = ()
    next_cursor: str | None = None

    @classmethod
    def from_dto(cls, dto: ConsolidationPageDto) -> ConsolidationListResponse:
        """The response for a handler result."""
        return cls(
            items=tuple(ConsolidationItemResponse.from_dto(i) for i in dto.items),
            next_cursor=dto.next_cursor,
        )

    def render(self) -> str:
        lines: list[str] = [item.line() for item in self.items] or ["no consolidations"]
        if self.next_cursor:
            lines.append(f"next: --cursor {self.next_cursor}")
        return "\n".join(lines)


class ConsolidationDecisionResponse(IRenderableResponse):
    """`noesis consolidation accept` and `reject`: every effect, or the preview of them.

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
    steps: tuple[ConsolidationStepResponse, ...] = ()
    progress: str
    replayed: bool = False

    @classmethod
    def from_dto(cls, dto: ConsolidationDecisionDto) -> ConsolidationDecisionResponse:
        """The response for a handler result."""
        return cls(
            consolidation_id=dto.consolidation_id,
            state=dto.state,
            preview=dto.preview,
            steps=tuple(ConsolidationStepResponse.from_dto(s) for s in dto.steps),
            progress=dto.progress,
            replayed=dto.replayed,
        )

    def render(self) -> str:
        lines: list[str] = [
            f"consolidation {self.consolidation_id}: {self.state}, progress {self.progress}"
            + (" (replayed: nothing written)" if self.replayed else "")
        ]
        for step in self.steps:
            code: str = f" [{step.error_code}]" if step.error_code else ""
            lines.append(f"{step.target_type} {step.target}: {step.outcome}{code}")
        if self.preview:
            lines.append("preview only: pass --yes to apply")
        return "\n".join(lines)
