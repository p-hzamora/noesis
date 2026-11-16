"""Reject a consolidation: dismiss it, then retract what it proposed, through C4."""

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDecisionDto,
    ConsolidationDto,
    ConsolidationStepDto,
    ReviewStateDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_assertion_handler import (
    RetractAssertionCommand,
    RetractAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RetractKnowledgeCommand,
    RetractKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.consolidation_support import (
    PROGRESS_VERSION,
    ConsolidationSupport,
    is_store_failure,
    partial_failure,
    progress_version_of,
)
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Assertion, Consolidation, Knowledge
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ConsolidationId,
    ConsolidationStateEnum,
    DismissalReasonKindEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.exceptions import (
    AppException,
    ConsolidationClosedError,
    ConsolidationNotFoundError,
    EntryAlreadyExistsError,
    RecordNotFoundError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

REJECT_CONSOLIDATION_COMMAND: str = "consolidation.reject"


class RejectConsolidationCommand(ReviewMutationCommand):
    """Dismiss a consolidation and retract what it proposed.

    Attributes:
        consolidation_id: The consolidation.
        reason_kind: `distinct` remembers the pairs judged; `poor_draft` and `other` do not.
        reason: Why; required.
    """

    consolidation_id: ConsolidationId
    reason_kind: DismissalReasonKindEnum
    reason: str


class RejectConsolidationHandler(IHandler[RejectConsolidationCommand, ConsolidationDecisionDto]):
    """Prechecks authority, dismisses with a version check, then retracts the proposals.

    Dismissal is committed first and releases the members; the retractions are separate
    transactions, so the same key resumes them even though the aggregate is already dismissed.
    A target someone accepted meanwhile is left accepted, never retracted.
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        states: IReviewStateReadRepository,
        read_repository: IConsolidationReadRepository,
    ) -> None:
        self._support: ConsolidationSupport = ConsolidationSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema, states=states
        )
        self._read: IConsolidationReadRepository = read_repository
        self._retract_knowledge: RetractKnowledgeHandler = RetractKnowledgeHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._retract_assertion: RetractAssertionHandler = RetractAssertionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )

    async def handle(self, action: RejectConsolidationCommand) -> ConsolidationDecisionDto:
        """Preview, dismiss and retract, or resume.

        Raises:
            ConsolidationNotFoundError: No such consolidation in the space.
            ConsolidationClosedError: Acceptance already started.
            ReviewNotAuthorisedError: The actor may not decide a target (before any write).
            ConsolidationPartiallyAppliedError: A retraction failed after the dismissal committed.
        """
        support: ConsolidationSupport = self._support
        prelude: Prelude = await support.prelude(action, REJECT_CONSOLIDATION_COMMAND)
        space_id: SpaceId = prelude.space_id
        dto: ConsolidationDto | None = await self._read.get(action.consolidation_id, space_id)
        if dto is None:
            raise ConsolidationNotFoundError(
                f"No consolidation {action.consolidation_id.value} in this space.",
                {"consolidation_id": action.consolidation_id.value},
                next_steps=["Run `noesis consolidation list`."],
            )
        if prelude.replay is not None and prelude.replay.extra.get("status") == "complete":
            progress, _ = await support.progress_of(dto, space_id)
            return ConsolidationDecisionDto(
                consolidation_id=dto.id,
                state=dto.state,
                preview=False,
                steps=_stored_steps(prelude.replay),
                progress=progress.value,
                replayed=True,
            )
        if prelude.replay is None and dto.state == ConsolidationStateEnum.ACCEPTANCE_STARTED.value:
            raise ConsolidationClosedError(
                f"Consolidation {dto.id} already started acceptance; it can no longer be dismissed.",
                {"consolidation_id": dto.id, "state": dto.state},
                next_steps=["Retract the produced records by hand with `noesis review retract`."],
            )
        planned, refusal = await self._precheck(dto, action, space_id)
        if not action.apply:
            progress, _ = await support.progress_of(dto, space_id)
            return ConsolidationDecisionDto(
                consolidation_id=dto.id,
                state=dto.state,
                preview=True,
                steps=tuple(planned),
                progress=progress.value,
            )
        if refusal is not None:
            raise refusal
        entry: LedgerEntry = prelude.replay or await self._dismiss(action, prelude)
        return await self._run(action, prelude, entry, dto)

    async def _precheck(
        self, dto: ConsolidationDto, action: RejectConsolidationCommand, space_id: SpaceId
    ) -> tuple[list[ConsolidationStepDto], AppException | None]:
        steps: list[ConsolidationStepDto] = [
            ConsolidationStepDto(target=dto.id, target_type="consolidation", outcome="planned")
        ]
        refusal: AppException | None = None
        if dto.project_key is None:  # space-wide members: only the user decides
            try:
                ReviewAuthorityPolicy.check(action.actor, [Applicability()])
            except AppException as error:
                refusal = error
                steps[0] = ConsolidationStepDto(
                    target=dto.id,
                    target_type="consolidation",
                    outcome="not_authorised",
                    error_code=error.error_code,
                )
        targets: list[tuple[str, str]] = [
            *(("assertion", item) for item in dto.produced_assertion_ids),
            *([("knowledge", dto.successor_id)] if dto.successor_id else []),
        ]
        states: dict[str, ReviewStateDto] = {
            s.record_id: s
            for s in await self._support.states.get_states(
                [RecordId(value=target) for _, target in targets], space_id
            )
        }
        async with self._support.uow_factory() as uow:
            for kind, target in targets:
                status: str | None = states[target].status if target in states else None
                if status == RecordStatusEnum.RETRACTED.value:
                    steps.append(
                        ConsolidationStepDto(
                            target=target, target_type=kind, outcome="already_retracted"
                        )
                    )
                    continue
                if status in (RecordStatusEnum.ACCEPTED.value, RecordStatusEnum.SUPERSEDED.value):
                    steps.append(
                        ConsolidationStepDto(
                            target=target, target_type=kind, outcome="left_accepted"
                        )
                    )
                    continue
                try:
                    record: Knowledge | Assertion | None = (
                        await uow.knowledge.get(RecordId(value=target), space_id=space_id)
                        if kind == "knowledge"
                        else await uow.assertions.get_by_id(
                            RecordId(value=target), space_id=space_id
                        )
                    )
                    if record is None:
                        raise RecordNotFoundError(
                            f"No {kind} {target} in this space.", {"record_id": target}
                        )
                    ReviewAuthorityPolicy.check(action.actor, [record.applicability])
                except AppException as error:
                    refusal = refusal or error
                    steps.append(
                        ConsolidationStepDto(
                            target=target,
                            target_type=kind,
                            outcome="not_authorised",
                            error_code=error.error_code,
                        )
                    )
                    continue
                steps.append(
                    ConsolidationStepDto(target=target, target_type=kind, outcome="planned")
                )
        return steps, refusal

    async def _dismiss(self, action: RejectConsolidationCommand, prelude: Prelude) -> LedgerEntry:
        """Dismiss with a version check and record the pending command, in one transaction."""
        support: ConsolidationSupport = self._support
        try:
            async with support.uow_factory() as uow:
                aggregate: Consolidation | None = await uow.consolidations.get_for_update(
                    action.consolidation_id, space_id=prelude.space_id
                )
                if aggregate is None:
                    raise ConsolidationNotFoundError(
                        f"No consolidation {action.consolidation_id.value} in this space.",
                        {"consolidation_id": action.consolidation_id.value},
                    )
                expected: int = aggregate.version
                if aggregate.dismiss(
                    reason_kind=action.reason_kind,
                    reason=SecretRedactor.redact(action.reason)[0],
                    actor=action.actor,
                    now=support.clock.now(),
                ):
                    await uow.consolidations.save(aggregate, expected_version=expected)
                entry: LedgerEntry = LedgerEntry(
                    space_id=prelude.space_id,
                    key=action.idempotency_key or "",
                    command=REJECT_CONSOLIDATION_COMMAND,
                    fingerprint=prelude.fingerprint,
                    extra={
                        PROGRESS_VERSION: 1,
                        "consolidation_id": action.consolidation_id.value,
                        "status": "pending",
                        "steps": [],
                    },
                    recorded_at=support.clock.now(),
                )
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError as error:
            return await support.review.winner(error, action, REJECT_CONSOLIDATION_COMMAND, prelude)
        return entry

    async def _run(
        self,
        action: RejectConsolidationCommand,
        prelude: Prelude,
        entry: LedgerEntry,
        dto: ConsolidationDto,
    ) -> ConsolidationDecisionDto:
        support: ConsolidationSupport = self._support
        space_id: SpaceId = prelude.space_id
        steps: list[ConsolidationStepDto] = [
            ConsolidationStepDto(target=dto.id, target_type="consolidation", outcome="done")
        ]
        reason: str = SecretRedactor.redact(action.reason)[0]
        targets: list[tuple[str, str]] = [
            *(("assertion", item) for item in dto.produced_assertion_ids),
            *([("knowledge", dto.successor_id)] if dto.successor_id else []),
        ]
        retry: str = (
            f"Run `noesis consolidation reject {dto.id} --yes` again with "
            f"--idempotency-key {entry.key}."
        )
        for index, (kind, target) in enumerate(targets):
            try:
                outcome: str = await self._retract(
                    action, kind, RecordId(value=target), space_id, entry.key, reason
                )
                steps.append(ConsolidationStepDto(target=target, target_type=kind, outcome=outcome))
            except AppException as error:
                steps.append(
                    ConsolidationStepDto(
                        target=target,
                        target_type=kind,
                        outcome="failed",
                        error_code=error.error_code,
                    )
                )
                if is_store_failure(error):
                    steps.extend(
                        ConsolidationStepDto(target=rest, target_type=rest_kind, outcome="not_run")
                        for rest_kind, rest in targets[index + 1 :]
                    )
                    raise partial_failure(
                        consolidation_id=dto.id,
                        steps=steps,
                        progress="unknown",
                        retry=retry,
                        cause=error,
                    ) from error
        fresh: ConsolidationDto | None = await self._read.get(action.consolidation_id, space_id)
        progress, _ = await support.progress_of(fresh or dto, space_id)
        failures: bool = any(step.outcome == "failed" for step in steps)
        await self._save_progress(prelude, entry, steps, complete=not failures)
        if failures:
            raise partial_failure(
                consolidation_id=dto.id,
                steps=steps,
                progress=progress.value,
                retry=retry,
            )
        return ConsolidationDecisionDto(
            consolidation_id=dto.id,
            state=(fresh or dto).state,
            preview=False,
            steps=tuple(steps),
            progress=progress.value,
            replayed=prelude.replay is not None,
        )

    async def _retract(
        self,
        action: RejectConsolidationCommand,
        kind: str,
        target: RecordId,
        space_id: SpaceId,
        key: str,
        reason: str,
    ) -> str:
        """One C4 retraction, decided on the target's current state."""
        state: ReviewStateDto | None = next(
            iter(await self._support.states.get_states([target], space_id)), None
        )
        status: str | None = state.status if state else None
        if status == RecordStatusEnum.RETRACTED.value:
            return "already_retracted"
        if status in (RecordStatusEnum.ACCEPTED.value, RecordStatusEnum.SUPERSEDED.value):
            return "left_accepted"
        inner_key: str = f"{key}:reject:{target.value}"
        if kind == "knowledge":
            await self._retract_knowledge.handle(
                RetractKnowledgeCommand(
                    space_key=action.space_key,
                    actor=action.actor,
                    idempotency_key=inner_key,
                    record_id=target,
                    reason=reason,
                )
            )
        else:
            await self._retract_assertion.handle(
                RetractAssertionCommand(
                    space_key=action.space_key,
                    actor=action.actor,
                    idempotency_key=inner_key,
                    assertion_id=target,
                    reason=reason,
                )
            )
        return "rejected"

    async def _save_progress(
        self,
        prelude: Prelude,
        entry: LedgerEntry,
        steps: list[ConsolidationStepDto],
        *,
        complete: bool,
    ) -> None:
        extra: dict[str, JsonValue] = {
            **entry.extra,
            "status": "complete" if complete else "pending",
            "steps": [s.model_dump(mode="json") for s in steps],
        }
        try:
            async with self._support.uow_factory() as uow:
                await uow.ledger.update_extra(
                    prelude.space_id,
                    entry.key,
                    expected_progress_version=progress_version_of(entry),
                    extra=extra,
                )
                await uow.commit()
        except AppException as error:
            # A lost update (another run with this key moved on) always surfaces; an unreachable
            # store only hides the bookkeeping of a run that is already failing.
            if complete or not is_store_failure(error):
                raise


def _stored_steps(entry: LedgerEntry) -> tuple[ConsolidationStepDto, ...]:
    raw: JsonValue = entry.extra.get("steps")
    if not isinstance(raw, list):
        return ()
    return tuple(ConsolidationStepDto.model_validate(item) for item in raw)
