"""The flow every curation entry point shares: stage, probe, judge, plan, register, apply.

`curate brief`, `curate apply` and `curate retry` differ only in how a submission arrives; from
the staged ticket on, one flow runs (`20-curation.md`, Flows). The inbox is the only thing this
service writes itself; every graph write is a command handler's, called by the process manager.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import StrEnum

from noesis.bounded_context.knowledge.application.dtos import (
    CurationItemDto,
    CurationResultDto,
    CurationSourceDto,
    PlanRegistrationDto,
    RecordDto,
    RelatedLookupDto,
    RelatedRecordDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.register_curation_plan_handler import (
    RegisterCurationPlanCommand,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.curation import (
    CurationTicket,
    ICurationInbox,
    ICurator,
    IRelatedRecordFinder,
    StepOutcome,
)
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.services.curation_process_manager import (
    ApplyContext,
    CurationProcessManager,
)
from noesis.bounded_context.knowledge.application.services.curation_redactor import (
    CurationRedactor,
)
from noesis.bounded_context.knowledge.application.services.idempotency import read_ledger
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.services import (
    CaptureKeyPolicy,
    CurationAdmissionPolicy,
    CurationProgressPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    DEFAULT_CURATION_SUBTYPES,
    CurationCandidate,
    CurationFailureReasonEnum,
    CurationPlan,
    CurationProgress,
    CurationStageEnum,
    CurationSubmission,
    CurationTarget,
    Key,
    RecordId,
    SourceKindEnum,
    SpaceId,
    SubmissionKindEnum,
    WorkBrief,
)
from noesis.exceptions import (
    AppException,
    BriefAlreadyIngestedError,
    CurationParkedError,
    CuratorRunFailedError,
    GraphStoreUnavailableError,
    InvalidRecordIdError,
    ParkedCurationTicketNotFoundError,
    RelatedLookupUnavailableError,
    SpaceNotFoundError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

RELATED_RECORDS_LIMIT: int = 8
"""How many related records the curator gets."""

type Sleeper = Callable[[float], Awaitable[None]]


class RelatedLookupModeEnum(StrEnum):
    """Whether a brief's judgment starts with a related-record lookup."""

    REQUIRED = "required"
    OFF = "off"


class RunOptions(FrozenObject):
    """How one run behaves.

    Attributes:
        space_key: The active space.
        related_lookup: `required` fails closed when the lookup cannot answer; `off` skips it.
        max_attempts: Curator runs before giving up.
        park_on_failure: Whether a failure before the plan is saved keeps the ticket for a retry
            (a store failure always does).
        dry_run: Read and judge, write nothing, not even the inbox.
    """

    space_key: Key
    related_lookup: RelatedLookupModeEnum = RelatedLookupModeEnum.REQUIRED
    max_attempts: int = 2
    park_on_failure: bool = True
    dry_run: bool = False


class _Run:
    """The ticket of one run, as its progress moves."""

    def __init__(self, ticket: CurationTicket) -> None:
        self.ticket: CurationTicket = ticket
        self.related: RelatedLookupDto = ticket.related_lookup or RelatedLookupDto(state="disabled")
        self.work_brief_source_id: str | None = None

    @property
    def submission(self) -> CurationSubmission:
        return self.ticket.submission

    @property
    def id(self) -> str:
        return self.ticket.ticket


class CurationRunner:
    """Drives a submission from the inbox to the graph, or reports what it would do.

    Args:
        inbox: The local ticket state.
        curator: Judges briefs.
        finder: Looks up related records.
        records: The record read side (space, targets, related records).
        uow_factory: Opens a unit of work; used only to read the ledger.
        manager: Applies a registered plan.
        register: Registers a plan in the ledger.
        policy: The admission table.
        retry_delay_seconds: Pause between curator attempts.
        sleep: Awaited for that pause.
    """

    def __init__(
        self,
        *,
        inbox: ICurationInbox,
        curator: ICurator,
        finder: IRelatedRecordFinder,
        records: IRecordReadRepository,
        uow_factory: KnowledgeUnitOfWorkFactory,
        manager: CurationProcessManager,
        register: IHandler[RegisterCurationPlanCommand, PlanRegistrationDto],
        policy: CurationAdmissionPolicy,
        retry_delay_seconds: float,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._inbox: ICurationInbox = inbox
        self._curator: ICurator = curator
        self._finder: IRelatedRecordFinder = finder
        self._records: IRecordReadRepository = records
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._manager: CurationProcessManager = manager
        self._register: IHandler[RegisterCurationPlanCommand, PlanRegistrationDto] = register
        self._policy: CurationAdmissionPolicy = policy
        self._retry_delay_seconds: float = retry_delay_seconds
        self._sleep: Sleeper = sleep

    # ----- entry points -----

    async def run(self, submission: CurationSubmission, options: RunOptions) -> CurationResultDto:
        """Curate a new (or repeated) submission.

        Raises:
            GraphStoreUnavailableError: The store is down; the ticket is parked.
            CurationParkedError: The curator or a step failed; the ticket is parked.
            RelatedLookupUnavailableError: The lookup is required and cannot answer.
            BriefAlreadyIngestedError: The plan is registered but no local plan matches it.
            CurationInboxFailedError: The inbox cannot be read, written or locked.
        """
        if options.dry_run:
            return await self._dry_run(submission, options)
        ticket_id: str = CaptureKeyPolicy.ticket_of(submission.submission_key)
        async with self._inbox.locked(ticket_id):
            return await self._drive(await self._inbox.stage(submission), options)

    async def retry(self, ticket_id: str, options: RunOptions) -> CurationResultDto:
        """Run a parked (or any) ticket again from the stage it failed at.

        Raises:
            ParkedCurationTicketNotFoundError: No such ticket.
            The same errors as `run`.
        """
        async with self._inbox.locked(ticket_id):
            ticket: CurationTicket | None = await self._inbox.get(ticket_id)
            if ticket is None:
                raise ParkedCurationTicketNotFoundError(
                    f"No curation ticket {ticket_id!r}.",
                    {"ticket": ticket_id},
                    next_steps=["Run `noesis curate parked` to list the tickets."],
                )
            return await self._drive(ticket, options)

    # ----- the flow -----

    async def _drive(self, ticket: CurationTicket, options: RunOptions) -> CurationResultDto:
        run: _Run = _Run(ticket)
        if ticket.progress.is_failed:
            await self._move(run, CurationProgressPolicy.resume(ticket.progress))
        try:
            return await self._flow(run, options)
        except GraphStoreUnavailableError as error:
            await self._fail(run, CurationFailureReasonEnum.STORE_UNAVAILABLE)
            error.metadata["ticket"] = run.id
            error.next_steps = (*error.next_steps, _retry_hint(run.id))
            raise

    async def _flow(self, run: _Run, options: RunOptions) -> CurationResultDto:
        submission: CurationSubmission = run.submission
        space_id: SpaceId = await self._space_id(options.space_key)
        entry: LedgerEntry | None = await read_ledger(
            self._uow_factory, space_id, CaptureKeyPolicy.plan_key(submission.submission_key)
        )
        if run.ticket.plan is not None and run.ticket.progress.stage is CurationStageEnum.STAGED:
            await self._advance(run, CurationStageEnum.PLANNED)
        if entry is not None:
            plan: CurationPlan | None = run.ticket.plan
            if plan is None or plan.plan_hash() != entry.fingerprint:
                await self._inbox.remove(run.id)  # Q-015: a ticket that cannot proceed is dropped
                raise BriefAlreadyIngestedError(
                    "This work was already ingested, but its plan is not available here.",
                    {
                        "submission_key": submission.submission_key,
                        "work_brief_source_id": entry.record_id.value if entry.record_id else None,
                    },
                    next_steps=[
                        "Run `noesis record get` on the `work_brief` Source named in the metadata."
                    ],
                )
            run.work_brief_source_id = entry.record_id.value if entry.record_id else None
            if run.ticket.progress.stage is CurationStageEnum.PLANNED:
                await self._advance(run, CurationStageEnum.APPLYING)
            return await self._apply(run, options, space_id, replayed=True)
        if run.ticket.plan is None:
            await self._judge_and_plan(run, options, space_id)
        registration: PlanRegistrationDto = await self._register.handle(
            RegisterCurationPlanCommand(
                space_key=options.space_key,
                submission_key=submission.submission_key,
                plan_hash=_plan_of(run).plan_hash(),
            )
        )
        run.work_brief_source_id = registration.source_id
        if run.ticket.progress.stage is CurationStageEnum.PLANNED:
            await self._advance(run, CurationStageEnum.APPLYING)
        return await self._apply(run, options, space_id, replayed=registration.replayed)

    async def _judge_and_plan(self, run: _Run, options: RunOptions, space_id: SpaceId) -> None:
        submission: CurationSubmission = run.submission
        candidates: tuple[CurationCandidate, ...] = submission.candidates
        if submission.kind is SubmissionKindEnum.BRIEF:
            candidates = await self._judge_brief(run, options, space_id)
        plan: CurationPlan = await self._plan_of_candidates(
            candidates, submission.project_key, space_id
        )
        await self._inbox.save_plan(run.id, plan, related_lookup=run.related)
        await self._advance(run, CurationStageEnum.PLANNED)

    async def _apply(
        self, run: _Run, options: RunOptions, space_id: SpaceId, *, replayed: bool
    ) -> CurationResultDto:
        plan: CurationPlan = _plan_of(run)
        ticket: CurationTicket = run.ticket
        recorded: Mapping[tuple[int, str], StepOutcome] = {
            (item.ordinal, item.step): item for item in ticket.steps
        }

        async def record(outcome: StepOutcome) -> None:
            await self._inbox.record_step(run.id, outcome)

        try:
            items: tuple[CurationItemDto, ...] = await self._manager.apply(
                plan,
                _context(run.submission, options.space_key),
                recorded=recorded,
                record=record,
            )
        except GraphStoreUnavailableError:
            raise
        except AppException as error:
            await self._fail(
                run, CurationFailureReasonEnum.STEP_FAILED, error_code=error.error_code
            )
            raise CurationParkedError(
                f"A step of the curation failed: {error.message}",
                {
                    "ticket": run.id,
                    "repository": run.submission.project_key,
                    "cause": error.error_code,
                    "cause_metadata": _json_metadata(error.metadata),
                },
                next_steps=[f"Fix the cause, then run `noesis curate retry {run.id}`."],
            ) from error
        if run.ticket.progress.stage is CurationStageEnum.APPLYING:
            await self._advance(run, CurationStageEnum.APPLIED)
        return CurationResultDto(
            ticket=run.id,
            submission_key=run.submission.submission_key,
            replayed=replayed,
            items=items,
            sources=await self._sources(run.submission, run.work_brief_source_id, items, space_id),
            related_lookup=run.related,
        )

    # ----- judging -----

    async def _judge_brief(
        self, run: _Run, options: RunOptions, space_id: SpaceId
    ) -> tuple[CurationCandidate, ...]:
        brief: WorkBrief | None = run.submission.brief
        if brief is None:
            raise CuratorRunFailedError("The submission holds no brief to judge.")
        related: list[RelatedRecordDto] = []
        run.related = RelatedLookupDto(state="disabled")
        if options.related_lookup is RelatedLookupModeEnum.REQUIRED:
            try:
                related, pending = await self._related(brief, space_id)
            except RelatedLookupUnavailableError as error:
                await self._abandon(
                    run,
                    options,
                    CurationFailureReasonEnum.RELATED_LOOKUP_UNAVAILABLE,
                    error,
                )
                raise
            run.related = RelatedLookupDto(state="used", pending_changes=pending)
        try:
            return await self._attempt_curator(brief, related, options)
        except CuratorRunFailedError as error:
            await self._abandon(run, options, CurationFailureReasonEnum.CURATOR_FAILED, error)
            if not options.park_on_failure:
                raise
            raise CurationParkedError(
                f"Curation failed after {options.max_attempts} attempt(s): {error.message}",
                {
                    "ticket": run.id,
                    "repository": run.submission.project_key,
                    "cause": error.error_code,
                },
                next_steps=[
                    *error.next_steps,
                    f"Fix the cause, then run `noesis curate retry {run.id}`.",
                ],
            ) from error

    async def _attempt_curator(
        self, brief: WorkBrief, related: Sequence[RelatedRecordDto], options: RunOptions
    ) -> tuple[CurationCandidate, ...]:
        """Judge with up to `max_attempts` runs, pausing between them."""
        last: CuratorRunFailedError | None = None
        for attempt in range(1, options.max_attempts + 1):
            try:
                return await self._curator.judge(brief, related, DEFAULT_CURATION_SUBTYPES)
            except CuratorRunFailedError as error:
                last = error
                if attempt < options.max_attempts:
                    await self._sleep(self._retry_delay_seconds)
        raise last or CuratorRunFailedError("The curator was never run.")

    async def _abandon(
        self,
        run: _Run,
        options: RunOptions,
        reason: CurationFailureReasonEnum,
        error: AppException,
    ) -> None:
        """A failure before the plan exists: park the ticket, or drop it with `--no-park`."""
        if options.park_on_failure:
            await self._fail(run, reason)
            error.metadata["ticket"] = run.id
            error.next_steps = (*error.next_steps, _retry_hint(run.id))
        else:
            await self._inbox.remove(run.id)

    async def _related(
        self, brief: WorkBrief, space_id: SpaceId
    ) -> tuple[list[RelatedRecordDto], int]:
        """The related records and the index lag; any failure but a down store is 'unavailable'."""
        try:
            found = await self._finder.find(
                brief.search_text(),
                space_id=space_id.value,
                project_key=brief.repository,
                limit=RELATED_RECORDS_LIMIT,
            )
            related: list[RelatedRecordDto] = []
            for hit in found.hits:
                described: RelatedRecordDto | None = await self._describe(hit.record_id, space_id)
                if described is not None:
                    related.append(described)
        except GraphStoreUnavailableError:
            raise
        except Exception as error:
            raise RelatedLookupUnavailableError(
                f"The related-record lookup is unavailable: {error}",
                {"cause": type(error).__name__},
                next_steps=[
                    "Run `noesis index status`; retry, or run with `--no-related` "
                    "or NOESIS_CURATOR_RELATED_LOOKUP=off."
                ],
            ) from error
        return related, found.pending_changes

    async def _describe(self, record_id: str, space_id: SpaceId) -> RelatedRecordDto | None:
        record: RecordDto | None = await self._records.get_by_id(
            RecordId(value=record_id), space_id=space_id
        )
        if record is None:
            return None
        return RelatedRecordDto(
            record_id=record.id,
            record_type=record.type,
            subtype=record.subtype,
            title=record.revision.title if record.revision is not None else None,
            status=record.effective_status or record.status,
            project_key=await self._project_key(record.project_id, space_id),
            revision=record.head_revision,
        )

    async def _plan_of_candidates(
        self, candidates: Sequence[CurationCandidate], project_key: str, space_id: SpaceId
    ) -> CurationPlan:
        redacted: tuple[CurationCandidate, ...] = tuple(
            CurationRedactor.candidate(candidate) for candidate in candidates
        )
        targets: dict[str, CurationTarget] = {}
        for candidate in redacted:
            if candidate.target_record_id and candidate.target_record_id not in targets:
                target: CurationTarget | None = await self._target(
                    candidate.target_record_id, space_id
                )
                if target is not None:
                    targets[candidate.target_record_id] = target
        return self._policy.plan(redacted, project_key=project_key, targets=targets)

    async def _target(self, record_id: str, space_id: SpaceId) -> CurationTarget | None:
        try:
            record: RecordDto | None = await self._records.get_by_id(
                RecordId(value=record_id), space_id=space_id
            )
        except InvalidRecordIdError:
            return None
        if record is None:
            return None
        return CurationTarget(
            record_id=record.id,
            record_type=record.type,
            status=record.effective_status or record.status,
            project_key=await self._project_key(record.project_id, space_id),
            head_revision=record.head_revision,
            tags=record.applicability.tags if record.applicability is not None else (),
        )

    async def _project_key(self, project_id: str | None, space_id: SpaceId) -> str | None:
        if project_id is None:
            return None
        project: RecordDto | None = await self._records.get_by_id(
            RecordId(value=project_id), space_id=space_id
        )
        return project.key if project is not None else None

    # ----- dry run -----

    async def _dry_run(
        self, submission: CurationSubmission, options: RunOptions
    ) -> CurationResultDto:
        """Read the store, look up, judge and plan; write nothing, not even the inbox."""
        space_id: SpaceId = await self._space_id(options.space_key)
        candidates: tuple[CurationCandidate, ...] = submission.candidates
        related_state: RelatedLookupDto = RelatedLookupDto(state="disabled")
        if submission.kind is SubmissionKindEnum.BRIEF and submission.brief is not None:
            related: list[RelatedRecordDto] = []
            if options.related_lookup is RelatedLookupModeEnum.REQUIRED:
                related, pending = await self._related(submission.brief, space_id)
                related_state = RelatedLookupDto(state="used", pending_changes=pending)
            candidates = await self._attempt_curator(submission.brief, related, options)
        plan: CurationPlan = await self._plan_of_candidates(
            candidates, submission.project_key, space_id
        )
        return CurationResultDto(
            submission_key=submission.submission_key,
            dry_run=True,
            items=CurationProcessManager.preview(plan),
            sources=tuple(
                CurationSourceDto(kind=source.kind.value, locator=source.locator)
                for source in _sources_of(submission)
                if isinstance(source, NewSourceInput)
            ),
            related_lookup=related_state,
        )

    # ----- results -----

    async def _sources(
        self,
        submission: CurationSubmission,
        work_brief_source_id: str | None,
        items: Sequence[CurationItemDto],
        space_id: SpaceId,
    ) -> tuple[CurationSourceDto, ...]:
        """The sources of every write, with the ids the store gave them."""
        ids: dict[tuple[str, str], str] = {}
        if work_brief_source_id is not None:
            ids[(SourceKindEnum.WORK_BRIEF.value, submission.submission_key)] = work_brief_source_id
        for item in items:
            if item.record_id is None:
                continue
            record: RecordDto | None = await self._records.get_by_id(
                RecordId(value=item.record_id), space_id=space_id
            )
            if record is not None and record.sources:
                ids.update({(source.kind, source.locator): source.id for source in record.sources})
                break
        return tuple(
            CurationSourceDto(
                id=ids.get((source.kind.value, source.locator)),
                kind=source.kind.value,
                locator=source.locator,
            )
            for source in _sources_of(submission)
            if isinstance(source, NewSourceInput)
        )

    # ----- ticket helpers -----

    async def _space_id(self, key: Key) -> SpaceId:
        space_id: SpaceId | None = await self._records.get_space_id(key)
        if space_id is None:
            raise SpaceNotFoundError(
                f"No knowledge space has the key {key.value!r}.",
                {"space_key": key.value},
                next_steps=["Run `noesis store init` or check the configured space key."],
            )
        return space_id

    async def _advance(self, run: _Run, to: CurationStageEnum) -> None:
        await self._move(run, CurationProgressPolicy.advance(run.ticket.progress, to))

    async def _fail(
        self,
        run: _Run,
        reason: CurationFailureReasonEnum,
        *,
        error_code: str | None = None,
    ) -> None:
        await self._move(
            run, CurationProgressPolicy.fail(run.ticket.progress, reason, error_code=error_code)
        )

    async def _move(self, run: _Run, to: CurationProgress) -> None:
        run.ticket = await self._inbox.advance(run.id, run.ticket.progress, to)


def _plan_of(run: _Run) -> CurationPlan:
    plan: CurationPlan | None = run.ticket.plan
    if plan is None:
        raise CurationParkedError(
            "The ticket has no plan.", {"ticket": run.id}
        )  # pragma: no cover - the flow saves the plan before it reads it
    return plan


def _sources_of(submission: CurationSubmission) -> tuple[SourceInput, ...]:
    """The sources every write cites: the work brief, each commit, the agent session."""
    return (
        NewSourceInput(kind=SourceKindEnum.WORK_BRIEF, locator=submission.submission_key),
        *(
            NewSourceInput(kind=SourceKindEnum.COMMIT, locator=sha)
            for sha in submission.commit_shas
        ),
        NewSourceInput(kind=SourceKindEnum.AGENT_SESSION, locator=submission.session_id),
    )


def _context(submission: CurationSubmission, space_key: Key) -> ApplyContext:
    return ApplyContext(
        space_key=space_key,
        actor=submission.actor,
        project=ProjectRef(key=Key(value=submission.project_key)),
        session_id=submission.session_id,
        submission_key=submission.submission_key,
        sources=_sources_of(submission),
    )


def _retry_hint(ticket: str) -> str:
    return f"Run `noesis curate retry {ticket}` once the cause is fixed."


def _json_metadata(metadata: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return dict(metadata)
