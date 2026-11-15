"""Reject a proposed assertion or retract an accepted one."""

from noesis.bounded_context.knowledge.application.dtos import RetractResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RETRACT_COMMAND,
    RequiredReason,
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
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, RecordStatusEnum
from noesis.exceptions import EntryAlreadyExistsError, RecordNotFoundError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock


class RetractAssertionCommand(ReviewMutationCommand):
    """Reject or retract one assertion.

    Attributes:
        assertion_id: The assertion.
        reason: Why; required.
    """

    assertion_id: RecordId
    reason: RequiredReason


class RetractAssertionHandler(IHandler[RetractAssertionCommand, RetractResultDto]):
    """Rejects a proposed assertion, retracts an accepted one; its live statement is freed."""

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

    async def handle(self, action: RetractAssertionCommand) -> RetractResultDto:
        """Reject, retract, preview, or replay the earlier identical request.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            RecordNotFoundError: No such assertion in the space.
            ReviewNotAuthorisedError: The actor may not decide this scope.
            InvalidStatusTransitionError: The assertion is neither `proposed` nor `accepted`.
            StatusConflictError: A concurrent decision won.
        """
        support: ReviewSupport = self._support
        prelude: Prelude = await support.prelude(action, RETRACT_COMMAND)
        if prelude.replay is not None:
            return result_from(prelude.replay, RetractResultDto)
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
                    uow, action, RETRACT_COMMAND, prelude
                )
                if raced is not None:
                    return result_from(raced, RetractResultDto)
                ReviewAuthorityPolicy.check(action.actor, [assertion.applicability])
                proposal: bool = assertion.status is RecordStatusEnum.PROPOSED
                basis = ReviewAuthorityPolicy.basis_for(action.actor)
                now = support.clock.now()
                decision: ReviewDecision = (
                    assertion.reject(actor=action.actor, reason=action.reason, basis=basis, now=now)
                    if proposal
                    else assertion.retract(
                        actor=action.actor, reason=action.reason, basis=basis, now=now
                    )
                )
                result: RetractResultDto = RetractResultDto(
                    id=assertion.id.value,
                    status=assertion.status.value,
                    outcome="rejected" if proposal else "retracted",
                    applied=action.apply,
                    decision_seq=decision.seq,
                    space_id=prelude.space_id.value,
                )
                if not action.apply:
                    return result
                await uow.assertions.save(assertion)
                await uow.ledger.record(
                    LedgerEntry(
                        space_id=prelude.space_id,
                        key=action.idempotency_key or "",
                        command=RETRACT_COMMAND,
                        fingerprint=prelude.fingerprint,
                        record_id=assertion.id,
                        extra=result_extra(result),
                        recorded_at=now,
                    )
                )
                await uow.commit()
        except EntryAlreadyExistsError as error:
            winner: LedgerEntry = await support.winner(error, action, RETRACT_COMMAND, prelude)
            return result_from(winner, RetractResultDto)
        return result
