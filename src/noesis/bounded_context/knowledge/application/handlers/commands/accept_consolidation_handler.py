"""Accept a consolidation: decide the successor, then each `supersedes`, through C4."""

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDecisionDto,
    ConsolidationDto,
    ConsolidationStepDto,
    ReviewStateDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionCommand,
    AcceptAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeCommand,
    AcceptKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionCommand,
    ApplySupersessionHandler,
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
    RecordId,
    RecordReference,
    RecordStatusEnum,
    SpaceId,
)
from noesis.exceptions import (
    AppException,
    ConsolidationClosedError,
    ConsolidationNotFoundError,
    ConsolidationNotMaterialisedError,
    EntryAlreadyExistsError,
    RecordNotFoundError,
    ReferenceNotAcceptableError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

ACCEPT_CONSOLIDATION_COMMAND: str = "consolidation.accept"


class AcceptConsolidationCommand(ReviewMutationCommand):
    """Accept the successor and its assertions of one consolidation.

    Attributes:
        consolidation_id: The consolidation.
        reason: Why; stored on every decision it takes.
    """

    consolidation_id: ConsolidationId
    reason: str | None = None


class AcceptConsolidationHandler(IHandler[AcceptConsolidationCommand, ConsolidationDecisionDto]):
    """Prechecks every decision, marks acceptance started, then runs the C4 handlers in order.

    The decisions are separate transactions. A failure is reported with every step's outcome and
    the same command (same or new key) converges: a target that is already accepted is checked,
    not accepted twice, and a pending supersession effect is run.
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
        self._accept_knowledge: AcceptKnowledgeHandler = AcceptKnowledgeHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._accept_assertion: AcceptAssertionHandler = AcceptAssertionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._effect: ApplySupersessionHandler = ApplySupersessionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )

    async def handle(self, action: AcceptConsolidationCommand) -> ConsolidationDecisionDto:
        """Preview, accept, or resume.

        Raises:
            ConsolidationNotFoundError: No such consolidation in the space.
            ConsolidationNotMaterialisedError: Its proposals were never completed.
            ConsolidationClosedError: It was dismissed.
            ReviewNotAuthorisedError: The actor may not decide a target (before any write).
            EvidenceRequiredError: An agent and an assertion without evidence (before any write).
            ConsolidationPartiallyAppliedError: A decision failed after earlier ones committed.
        """
        support: ConsolidationSupport = self._support
        prelude: Prelude = await support.prelude(action, ACCEPT_CONSOLIDATION_COMMAND)
        space_id: SpaceId = prelude.space_id
        dto: ConsolidationDto = await self._load(action.consolidation_id, space_id)
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
        if prelude.replay is None:
            self._check_state(dto)
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
        entry: LedgerEntry = prelude.replay or await self._start(action, prelude)
        return await self._run(action, prelude, entry, dto)

    @staticmethod
    def _check_state(dto: ConsolidationDto) -> None:
        if dto.state == ConsolidationStateEnum.OPENED.value:
            raise ConsolidationNotMaterialisedError(
                f"Consolidation {dto.id} was opened but its proposals are incomplete.",
                {"consolidation_id": dto.id},
                next_steps=["Retry the propose command with the same idempotency key."],
            )
        if dto.state == ConsolidationStateEnum.DISMISSED.value:
            raise ConsolidationClosedError(
                f"Consolidation {dto.id} is dismissed; this decision is closed.",
                {"consolidation_id": dto.id, "state": dto.state},
                next_steps=["Run `noesis consolidation show` to see how it ended."],
            )

    async def _load(self, consolidation_id: ConsolidationId, space_id: SpaceId) -> ConsolidationDto:
        found: ConsolidationDto | None = await self._read.get(consolidation_id, space_id)
        if found is None:
            raise ConsolidationNotFoundError(
                f"No consolidation {consolidation_id.value} in this space.",
                {"consolidation_id": consolidation_id.value},
                next_steps=["Run `noesis consolidation list`."],
            )
        return found

    async def _precheck(
        self, dto: ConsolidationDto, action: AcceptConsolidationCommand, space_id: SpaceId
    ) -> tuple[list[ConsolidationStepDto], AppException | None]:
        """Planned steps, and the first refusal; nothing is written."""
        steps: list[ConsolidationStepDto] = []
        refusal: AppException | None = None
        targets: list[tuple[str, str]] = [
            ("knowledge", dto.successor_id or ""),
            *(("assertion", item) for item in dto.produced_assertion_ids),
        ]
        states: dict[str, ReviewStateDto] = {
            s.record_id: s
            for s in await self._support.states.get_states(
                [RecordId(value=target) for _, target in targets], space_id
            )
        }
        async with self._support.uow_factory() as uow:
            for kind, target in targets:
                state: ReviewStateDto | None = states.get(target)
                if state is not None and state.status == RecordStatusEnum.ACCEPTED.value:
                    steps.append(
                        ConsolidationStepDto(
                            target=target, target_type=kind, outcome="already_accepted"
                        )
                    )
                    continue
                try:
                    if kind == "knowledge":
                        record: Knowledge | None = await uow.knowledge.get(
                            RecordId(value=target), space_id=space_id
                        )
                        if record is None:
                            raise RecordNotFoundError(
                                f"No knowledge {target} in this space.", {"record_id": target}
                            )
                        ReviewAuthorityPolicy.check(action.actor, [record.applicability])
                    else:
                        assertion: Assertion | None = await uow.assertions.get_by_id(
                            RecordId(value=target), space_id=space_id
                        )
                        if assertion is None:
                            raise RecordNotFoundError(
                                f"No assertion {target} in this space.", {"record_id": target}
                            )
                        endpoints: list[RecordReference] = await uow.record_references.describe(
                            [assertion.object_id], space_id
                        )
                        governing: list[Applicability] = [assertion.applicability]
                        if endpoints:
                            governing.append(Applicability(project_id=endpoints[0].project_id))
                        ReviewAuthorityPolicy.check(action.actor, governing)
                        ReviewAuthorityPolicy.check_evidence(
                            action.actor, len(assertion.evidence_ids)
                        )
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

    async def _start(self, action: AcceptConsolidationCommand, prelude: Prelude) -> LedgerEntry:
        """Mark acceptance started and record the pending command in one transaction."""
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
                if aggregate.start_acceptance(now=support.clock.now()):
                    await uow.consolidations.save(aggregate, expected_version=expected)
                entry: LedgerEntry = LedgerEntry(
                    space_id=prelude.space_id,
                    key=action.idempotency_key or "",
                    command=ACCEPT_CONSOLIDATION_COMMAND,
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
            return await support.review.winner(error, action, ACCEPT_CONSOLIDATION_COMMAND, prelude)
        return entry

    async def _run(
        self,
        action: AcceptConsolidationCommand,
        prelude: Prelude,
        entry: LedgerEntry,
        dto: ConsolidationDto,
    ) -> ConsolidationDecisionDto:
        support: ConsolidationSupport = self._support
        space_id: SpaceId = prelude.space_id
        key: str = entry.key
        steps: list[ConsolidationStepDto] = []
        successor: str = dto.successor_id or ""
        reason: str | None = SecretRedactor.redact(action.reason)[0] if action.reason else None
        retry: str = (
            f"Run `noesis consolidation accept {dto.id} --yes` again with --idempotency-key {key}."
        )
        failed_successor: bool = False
        targets: list[tuple[str, str]] = [
            ("knowledge", successor),
            *(("assertion", item) for item in dto.produced_assertion_ids),
        ]
        for index, (kind, target) in enumerate(targets):
            if kind == "assertion" and failed_successor:
                steps.append(
                    ConsolidationStepDto(target=target, target_type=kind, outcome="not_run")
                )
                continue
            try:
                outcome: str = await self._decide(
                    action, kind, RecordId(value=target), space_id, key, reason, dto
                )
                steps.append(ConsolidationStepDto(target=target, target_type=kind, outcome=outcome))
            except AppException as error:
                failed_successor = failed_successor or kind == "knowledge"
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
        fresh: ConsolidationDto = await self._load(action.consolidation_id, space_id)
        progress, _ = await support.progress_of(fresh, space_id)
        failures: list[ConsolidationStepDto] = [s for s in steps if s.outcome == "failed"]
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
            state=fresh.state,
            preview=False,
            steps=tuple(steps),
            progress=progress.value,
            replayed=prelude.replay is not None,
        )

    async def _decide(
        self,
        action: AcceptConsolidationCommand,
        kind: str,
        target: RecordId,
        space_id: SpaceId,
        key: str,
        reason: str | None,
        dto: ConsolidationDto,
    ) -> str:
        """One C4 decision; an accepted target is checked, never accepted twice."""
        state: ReviewStateDto | None = next(
            iter(await self._support.states.get_states([target], space_id)), None
        )
        accepted: bool = state is not None and state.status == RecordStatusEnum.ACCEPTED.value
        inner_key: str = f"{key}:accept:{target.value}"
        if kind == "knowledge":
            if accepted:
                return "already_accepted"
            await self._accept_knowledge.handle(
                AcceptKnowledgeCommand(
                    space_key=action.space_key,
                    actor=action.actor,
                    idempotency_key=inner_key,
                    record_id=target,
                    expected_revision=state.head_revision if state else None,
                    reason=reason,
                )
            )
            return "accepted"
        if not accepted:
            await self._accept_assertion.handle(
                AcceptAssertionCommand(
                    space_key=action.space_key,
                    actor=action.actor,
                    idempotency_key=inner_key,
                    assertion_id=target,
                    reason=reason,
                )
            )
            return "accepted"
        return await self._converge(action, target, dto, space_id)

    async def _converge(
        self,
        action: AcceptConsolidationCommand,
        assertion: RecordId,
        dto: ConsolidationDto,
        space_id: SpaceId,
    ) -> str:
        """An accepted `supersedes` whose effect never ran gets its effect now (C4's repair)."""
        index: int = dto.produced_assertion_ids.index(assertion.value)
        original: RecordId = RecordId(value=dto.members[index].record_id)
        state: ReviewStateDto | None = next(
            iter(await self._support.states.get_states([original], space_id)), None
        )
        if state is not None and state.status == RecordStatusEnum.SUPERSEDED.value:
            return "already_accepted"
        effect = await self._effect.handle(
            ApplySupersessionCommand(
                space_key=action.space_key,
                actor=action.actor,
                assertion_id=assertion,
                object_id=original,
            )
        )
        if effect.outcome != "applied":
            raise ReferenceNotAcceptableError(
                f"The effect on {original.value} was skipped: {effect.reason}.",
                {"record_id": original.value, "reason": effect.reason},
            )
        return "already_accepted"

    async def _save_progress(
        self,
        prelude: Prelude,
        entry: LedgerEntry,
        steps: list[ConsolidationStepDto],
        *,
        complete: bool,
    ) -> None:
        """Remember the outcomes on the pending entry; a failure here never hides the result."""
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
