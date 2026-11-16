"""Runs the steps of a registered curation plan through Knowledge's command handlers.

The process manager writes no aggregate and holds no repository or unit of work (D-002): every
write is one command handler call, its own unit of work, with an idempotency key from
`CaptureKeyPolicy`. The ledger, not the manager, is the truth for which steps finished, so a
step that already ran returns its original result.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from noesis.bounded_context.knowledge.application.dtos import (
    CaptureResultDto,
    CurationItemDto,
    ProposeAssertionResultDto,
    ReviseResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.ports.curation import (
    StepOutcome,
    StepOutcomeEnum,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.domain.services import CaptureKeyPolicy
from noesis.bounded_context.knowledge.domain.services.capture_key_policy import (
    STEP_EXPERIENCE,
    STEP_KNOWLEDGE,
    STEP_REVISE,
    STEP_SUPERSEDES,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    CandidateKindEnum,
    CurationPlan,
    ExperienceSubtypeEnum,
    Key,
    PlanEntry,
    ProposeKnowledge,
    ProposeSuccessor,
    RecordExperience,
    RecordId,
    RecordTypeEnum,
    ReviseProposal,
    Skip,
    Slug,
)
from noesis.exceptions import KnowledgeNotRevisableError, RevisionConflictError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

TARGET_CHANGED: str = "target_changed"

type StepHook = Callable[[int, str], Awaitable[None]]
"""Called before every step with its ordinal and name; raising fails the step (tests, tracing)."""

type StepRecorder = Callable[[StepOutcome], Awaitable[None]]
"""Called after every step with how it ended, so the ticket can keep it."""


class ApplyContext(FrozenObject):
    """What every write of one submission shares.

    Attributes:
        space_key: The active space.
        actor: Who the writes are made as.
        project: The project every write is scoped to.
        session_id: The agent session recorded on an experience.
        submission_key: The submission's key, the base of every idempotency key.
        sources: The sources every write cites: `work_brief`, `commit`s, `agent_session`.
    """

    space_key: Key
    actor: Actor
    project: ProjectRef
    session_id: str
    submission_key: str
    sources: tuple[SourceInput, ...]


@dataclass(slots=True)
class _EntryState:
    """What the steps of one entry produced."""

    record_id: str | None = None
    record_type: str | None = None
    revision: int | None = None
    status: str | None = None
    assertion_ids: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


class CurationProcessManager:
    """Applies a plan: records and revisions first, then the assertions that link them.

    Args:
        capture_experience: C2's `CaptureExperience`.
        capture_knowledge: C2's `CaptureKnowledge`.
        revise_knowledge: C2's `ReviseKnowledge`.
        propose_assertion: C4's `ProposeAssertion`; None when C4 is not built (no assertion
            steps run).
        step_hook: Called before each step.
    """

    def __init__(
        self,
        *,
        capture_experience: IHandler[CaptureExperienceCommand, CaptureResultDto],
        capture_knowledge: IHandler[CaptureKnowledgeCommand, CaptureResultDto],
        revise_knowledge: IHandler[ReviseKnowledgeCommand, ReviseResultDto],
        propose_assertion: IHandler[ProposeAssertionCommand, ProposeAssertionResultDto] | None,
        step_hook: StepHook | None = None,
    ) -> None:
        self._capture_experience = capture_experience
        self._capture_knowledge = capture_knowledge
        self._revise_knowledge = revise_knowledge
        self._propose_assertion = propose_assertion
        self._step_hook: StepHook | None = step_hook

    async def apply(
        self,
        plan: CurationPlan,
        context: ApplyContext,
        *,
        recorded: Mapping[tuple[int, str], StepOutcome],
        record: StepRecorder | None = None,
    ) -> tuple[CurationItemDto, ...]:
        """Run every step of `plan`, in plan order, and report what each candidate became.

        Args:
            plan: The registered plan.
            context: What every write shares.
            recorded: Step outcomes the ticket already holds, by (ordinal, step); a step recorded
                as skipped is not run again.
            record: Receives how each step ended.

        Raises:
            Exception: Whatever a handler raises, unchanged, except a revise conflict, which ends
                that step as `skipped: target_changed`.
        """
        states: dict[int, _EntryState] = {entry.ordinal: _EntryState() for entry in plan.entries}
        for entry in plan.entries:
            await self._write_record(entry, context, states[entry.ordinal], recorded, record)
        for entry in plan.entries:
            await self._write_assertions(entry, context, states, record)
        return tuple(_item(entry, states[entry.ordinal]) for entry in plan.entries)

    @staticmethod
    def preview(plan: CurationPlan) -> tuple[CurationItemDto, ...]:
        """What the plan would do, with no ids: the items of a dry run."""
        return tuple(_item(entry, _EntryState()) for entry in plan.entries)

    async def _write_record(
        self,
        entry: PlanEntry,
        context: ApplyContext,
        state: _EntryState,
        recorded: Mapping[tuple[int, str], StepOutcome],
        record: StepRecorder | None,
    ) -> None:
        write = entry.write
        candidate = entry.candidate
        key = CaptureKeyPolicy.step_key
        match write:
            case RecordExperience():
                result: CaptureResultDto = await self._step(
                    entry.ordinal,
                    STEP_EXPERIENCE,
                    record,
                    lambda: self._capture_experience.handle(
                        CaptureExperienceCommand(
                            idempotency_key=key(
                                context.submission_key, entry.ordinal, STEP_EXPERIENCE
                            ),
                            space_key=context.space_key,
                            subtype=ExperienceSubtypeEnum(candidate.subtype or ""),
                            body=candidate.body or "",
                            actor=context.actor,
                            project=context.project,
                            session=context.session_id,
                            sources=context.sources,
                        )
                    ),
                )
                _fill_from_capture(state, result)
            case ProposeKnowledge() | ProposeSuccessor():
                result = await self._step(
                    entry.ordinal,
                    STEP_KNOWLEDGE,
                    record,
                    lambda: self._capture_knowledge.handle(
                        CaptureKnowledgeCommand(
                            idempotency_key=key(
                                context.submission_key, entry.ordinal, STEP_KNOWLEDGE
                            ),
                            space_key=context.space_key,
                            title=candidate.title or "",
                            body=candidate.body or "",
                            subtype=Slug(value=candidate.subtype or ""),
                            actor=context.actor,
                            project=context.project,
                            sources=context.sources,
                        )
                    ),
                )
                _fill_from_capture(state, result)
            case ReviseProposal():
                await self._revise(entry, write, context, state, recorded, record)
            case Skip():
                return

    async def _revise(
        self,
        entry: PlanEntry,
        write: ReviseProposal,
        context: ApplyContext,
        state: _EntryState,
        recorded: Mapping[tuple[int, str], StepOutcome],
        record: StepRecorder | None,
    ) -> None:
        earlier: StepOutcome | None = recorded.get((entry.ordinal, STEP_REVISE))
        if earlier is not None and earlier.outcome is StepOutcomeEnum.SKIPPED:
            state.skipped_reason = earlier.reason or TARGET_CHANGED
            return
        try:
            revised: ReviseResultDto = await self._step(
                entry.ordinal,
                STEP_REVISE,
                record,
                lambda: self._revise_knowledge.handle(
                    ReviseKnowledgeCommand(
                        idempotency_key=CaptureKeyPolicy.step_key(
                            context.submission_key, entry.ordinal, STEP_REVISE
                        ),
                        space_key=context.space_key,
                        record_id=RecordId(value=write.target_record_id),
                        expected_revision=write.expected_revision,
                        actor=context.actor,
                        title=entry.candidate.title,
                        body=entry.candidate.body,
                        sources=context.sources,
                    )
                ),
            )
        except RevisionConflictError, KnowledgeNotRevisableError:
            state.skipped_reason = TARGET_CHANGED
            if record is not None:
                await record(
                    StepOutcome(
                        ordinal=entry.ordinal,
                        step=STEP_REVISE,
                        outcome=StepOutcomeEnum.SKIPPED,
                        reason=TARGET_CHANGED,
                    )
                )
            return
        state.record_id = revised.record_id
        state.record_type = RecordTypeEnum.KNOWLEDGE.value
        state.revision = revised.revision
        state.status = revised.status

    async def _write_assertions(
        self,
        entry: PlanEntry,
        context: ApplyContext,
        states: Mapping[int, _EntryState],
        record: StepRecorder | None,
    ) -> None:
        write = entry.write
        state: _EntryState = states[entry.ordinal]
        handler = self._propose_assertion
        if handler is None or state.record_id is None:
            return
        if isinstance(write, ProposeSuccessor):
            state.assertion_ids.append(
                await self._propose(
                    handler,
                    entry,
                    STEP_SUPERSEDES,
                    context,
                    record,
                    predicate=AssertionPredicateEnum.SUPERSEDES,
                    subject_id=state.record_id,
                    object_id=write.target_record_id,
                    evidence_ids=(),
                )
            )
        if isinstance(write, ProposeKnowledge | ReviseProposal | ProposeSuccessor):
            for evidence_ordinal in write.evidence_ordinals:
                evidence: _EntryState | None = states.get(evidence_ordinal)
                if evidence is None or evidence.record_id is None:
                    continue
                state.assertion_ids.append(
                    await self._propose(
                        handler,
                        entry,
                        CaptureKeyPolicy.supports_step(evidence_ordinal),
                        context,
                        record,
                        predicate=AssertionPredicateEnum.SUPPORTS,
                        subject_id=evidence.record_id,
                        object_id=state.record_id,
                        evidence_ids=(evidence.record_id,),
                    )
                )

    async def _propose(
        self,
        handler: IHandler[ProposeAssertionCommand, ProposeAssertionResultDto],
        entry: PlanEntry,
        step: str,
        context: ApplyContext,
        record: StepRecorder | None,
        *,
        predicate: AssertionPredicateEnum,
        subject_id: str,
        object_id: str,
        evidence_ids: tuple[str, ...],
    ) -> str:
        result: ProposeAssertionResultDto = await self._step(
            entry.ordinal,
            step,
            record,
            lambda: handler.handle(
                ProposeAssertionCommand(
                    space_key=context.space_key,
                    actor=context.actor,
                    apply=True,
                    idempotency_key=CaptureKeyPolicy.step_key(
                        context.submission_key, entry.ordinal, step
                    ),
                    predicate=predicate,
                    subject_id=RecordId(value=subject_id),
                    object_id=RecordId(value=object_id),
                    evidence_ids=tuple(RecordId(value=item) for item in evidence_ids),
                    rationale=entry.candidate.reason or "",
                    project=context.project,
                    sources=context.sources,
                )
            ),
        )
        return result.id

    async def _step[TResult: CaptureResultDto | ReviseResultDto | ProposeAssertionResultDto](
        self,
        ordinal: int,
        step: str,
        record: StepRecorder | None,
        call: Callable[[], Awaitable[TResult]],
    ) -> TResult:
        """One step: the hook, the handler call, and the recorded outcome."""
        if self._step_hook is not None:
            await self._step_hook(ordinal, step)
        result: TResult = await call()
        if record is not None:
            await record(
                StepOutcome(
                    ordinal=ordinal,
                    step=step,
                    outcome=StepOutcomeEnum.REPLAYED
                    if result.replayed
                    else StepOutcomeEnum.WRITTEN,
                )
            )
        return result


def _fill_from_capture(state: _EntryState, result: CaptureResultDto) -> None:
    state.record_id = result.record_id
    state.record_type = result.record_type
    state.revision = result.revision
    state.status = result.status


def _item(entry: PlanEntry, state: _EntryState) -> CurationItemDto:
    """The item of one entry, from what its steps produced (nothing, on a preview)."""
    candidate = entry.candidate
    write = entry.write
    base: dict[str, object] = {
        "ordinal": entry.ordinal,
        "candidate": candidate.key or f"#{entry.ordinal}",
        "kind": candidate.kind.value if isinstance(candidate.kind, CandidateKindEnum) else None,
        "record_id": state.record_id,
        "revision": state.revision,
        "status": state.status,
        "assertion_ids": tuple(state.assertion_ids),
    }
    match write:
        case Skip():
            return CurationItemDto.model_validate(
                {**base, "outcome": "skipped", "reason": write.reason}
            )
        case RecordExperience():
            return CurationItemDto.model_validate(
                {**base, "outcome": "recorded", "type": RecordTypeEnum.EXPERIENCE.value}
            )
        case ProposeKnowledge():
            return CurationItemDto.model_validate(
                {
                    **base,
                    "outcome": "proposed",
                    "type": RecordTypeEnum.KNOWLEDGE.value,
                    "target_record_id": write.target_record_id,
                    "reason": write.reason,
                }
            )
        case ProposeSuccessor():
            return CurationItemDto.model_validate(
                {
                    **base,
                    "outcome": "successor_proposed",
                    "type": RecordTypeEnum.KNOWLEDGE.value,
                    "target_record_id": write.target_record_id,
                }
            )
        case ReviseProposal():
            if state.skipped_reason is not None:
                return CurationItemDto.model_validate(
                    {
                        **base,
                        "outcome": "skipped",
                        "target_record_id": write.target_record_id,
                        "reason": state.skipped_reason,
                    }
                )
            return CurationItemDto.model_validate(
                {
                    **base,
                    "outcome": "revised",
                    "type": RecordTypeEnum.KNOWLEDGE.value,
                    "target_record_id": write.target_record_id,
                }
            )
