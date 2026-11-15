"""Accept a proposed assertion; a `supersedes` then runs its effect in a second unit of work."""

from noesis.bounded_context.knowledge.application.dtos import AcceptResultDto, EffectDto
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    ACCEPT_COMMAND,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionCommand,
    ApplySupersessionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
    ReviewSupport,
    result_extra,
    result_from,
)
from noesis.bounded_context.knowledge.domain.entities import Assertion, ReviewDecision
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordReference,
    RecordStatusEnum,
    ReviewLifecycle,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    EntryAlreadyExistsError,
    RecordNotFoundError,
    ReferenceNotAcceptableError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

PENDING_EFFECT: str = "pending_effect"


class AcceptAssertionCommand(ReviewMutationCommand):
    """Accept one assertion.

    Attributes:
        assertion_id: The assertion to accept.
        reason: Why, when given.
    """

    assertion_id: RecordId
    reason: str | None = None


class AcceptAssertionHandler(IHandler[AcceptAssertionCommand, AcceptResultDto]):
    """Checks authority, evidence, lifecycle and endpoints; then decides and runs the effect."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self._support: ReviewSupport = ReviewSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._effect: ApplySupersessionHandler = ApplySupersessionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )

    async def handle(self, action: AcceptAssertionCommand) -> AcceptResultDto:
        """Accept, preview, or replay the earlier identical accept (completing a pending effect).

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            RecordNotFoundError: No such assertion in the space.
            ReviewNotAuthorisedError: The actor may not decide this scope.
            EvidenceRequiredError: An agent accepting an assertion without evidence.
            InvalidStatusTransitionError: The assertion is not `proposed`.
            ReferenceNotAcceptableError: An endpoint is not in an acceptable state.
            StatusConflictError: A concurrent decision won.
        """
        support: ReviewSupport = self._support
        prelude: Prelude = await support.prelude(action, ACCEPT_COMMAND)
        if prelude.replay is not None:
            return await self._with_effect(
                action, result_from(prelude.replay, AcceptResultDto), prelude.replay
            )
        try:
            async with support.uow_factory() as uow:
                assertion: Assertion | None = await uow.assertions.get_by_id(
                    action.assertion_id, space_id=prelude.space_id
                )
                if assertion is None:
                    raise RecordNotFoundError(
                        f"No assertion {action.assertion_id.value} in this space.",
                        {
                            "record_id": action.assertion_id.value,
                            "space_id": prelude.space_id.value,
                        },
                        next_steps=["Check the id and the active space."],
                    )
                raced: LedgerEntry | None = await support.raced(
                    uow, action, ACCEPT_COMMAND, prelude
                )
                if raced is not None:
                    return await self._with_effect(
                        action, result_from(raced, AcceptResultDto), raced
                    )
                supersedes: bool = assertion.predicate is AssertionPredicateEnum.SUPERSEDES
                endpoints: list[RecordReference] = await uow.record_references.describe(
                    [assertion.subject_id, assertion.object_id], prelude.space_id
                )
                by_id: dict[str, RecordReference] = {e.record_id.value: e for e in endpoints}
                governing: list[Applicability] = [assertion.applicability]
                if supersedes and assertion.object_id.value in by_id:
                    governing.append(
                        Applicability(project_id=by_id[assertion.object_id.value].project_id)
                    )
                ReviewAuthorityPolicy.check(action.actor, governing)
                ReviewAuthorityPolicy.check_evidence(action.actor, len(assertion.evidence_ids))
                ReviewLifecycle.next_status(ReviewTransitionEnum.ACCEPT, assertion.status)
                self._check_endpoints(assertion, by_id, supersedes=supersedes)
                decision: ReviewDecision = assertion.accept(
                    actor=action.actor,
                    reason=action.reason,
                    basis=ReviewAuthorityPolicy.basis_for(action.actor),
                    now=support.clock.now(),
                )
                result: AcceptResultDto = AcceptResultDto(
                    id=assertion.id.value,
                    type="assertion",
                    status=assertion.status.value,
                    decision_seq=decision.seq,
                    basis=decision.basis.value,
                    applied=action.apply,
                    space_id=prelude.space_id.value,
                )
                if not action.apply:
                    return result
                extra: dict[str, JsonValue] = result_extra(result)
                if supersedes:
                    extra[PENDING_EFFECT] = {"object_id": assertion.object_id.value}
                entry: LedgerEntry = LedgerEntry(
                    space_id=prelude.space_id,
                    key=action.idempotency_key or "",
                    command=ACCEPT_COMMAND,
                    fingerprint=prelude.fingerprint,
                    record_id=assertion.id,
                    extra=extra,
                    recorded_at=decision.decided_at,
                )
                await uow.assertions.save(assertion)
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError as error:
            winner: LedgerEntry = await support.winner(error, action, ACCEPT_COMMAND, prelude)
            return await self._with_effect(action, result_from(winner, AcceptResultDto), winner)
        return await self._with_effect(action, result, entry, replayed=False)

    @staticmethod
    def _check_endpoints(
        assertion: Assertion, by_id: dict[str, RecordReference], *, supersedes: bool
    ) -> None:
        acceptable: tuple[RecordStatusEnum, ...] = (
            (RecordStatusEnum.ACCEPTED,)
            if supersedes
            else (RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED)
        )
        for role, record_id in (("subject", assertion.subject_id), ("object", assertion.object_id)):
            reference: RecordReference | None = by_id.get(record_id.value)
            status: RecordStatusEnum | None = reference.effective_status if reference else None
            if reference is None or (status is not None and status not in acceptable):
                raise ReferenceNotAcceptableError(
                    f"The {role} {record_id.value} is "
                    f"{status.value if status else 'unknown'}; it cannot back an accepted assertion.",
                    {
                        "record_id": record_id.value,
                        "role": role,
                        "effective_status": status.value if status else None,
                    },
                    next_steps=["Accept the subject first."],
                )

    async def _with_effect(
        self,
        action: AcceptAssertionCommand,
        result: AcceptResultDto,
        entry: LedgerEntry,
        *,
        replayed: bool = True,
    ) -> AcceptResultDto:
        pending: JsonValue = entry.extra.get(PENDING_EFFECT)
        if not isinstance(pending, dict) or not isinstance(pending.get("object_id"), str):
            return result
        effect: EffectDto = await self._effect.handle(
            ApplySupersessionCommand(
                space_key=action.space_key,
                actor=action.actor,
                assertion_id=action.assertion_id,
                object_id=RecordId(value=pending["object_id"]),
            )
        )
        return result.model_copy(update={"effects": (effect,), "replayed": replayed})
