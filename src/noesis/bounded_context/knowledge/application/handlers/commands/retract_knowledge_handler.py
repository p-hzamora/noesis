"""Reject proposed Knowledge or retract accepted Knowledge."""

from typing import Annotated

from pydantic import AfterValidator

from noesis.bounded_context.knowledge.application.dtos import RetractResultDto
from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
    ReviewSupport,
    result_extra,
    result_from,
)
from noesis.bounded_context.knowledge.domain.entities import Knowledge, ReviewDecision
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, RecordStatusEnum
from noesis.exceptions import EntryAlreadyExistsError, RecordNotFoundError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock

RETRACT_COMMAND: str = "review.retract"


def _require_reason(value: str) -> str:
    if not value.strip():
        raise ValueError("A reason is required.")
    return value


type RequiredReason = Annotated[str, AfterValidator(_require_reason)]
"""A reason that is not blank, for the retract commands."""


class RetractKnowledgeCommand(ReviewMutationCommand):
    """Reject or retract one Knowledge record.

    Attributes:
        record_id: The knowledge.
        reason: Why; required.
    """

    record_id: RecordId
    reason: RequiredReason


class RetractKnowledgeHandler(IHandler[RetractKnowledgeCommand, RetractResultDto]):
    """Rejects a proposal, retracts accepted knowledge; one decision, one transaction."""

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

    async def handle(self, action: RetractKnowledgeCommand) -> RetractResultDto:
        """Reject, retract, preview, or replay the earlier identical request.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            RecordNotFoundError: No such knowledge in the space.
            ReviewNotAuthorisedError: The actor may not decide this scope.
            InvalidStatusTransitionError: The knowledge is neither `proposed` nor `accepted`.
            StatusConflictError: A concurrent decision won.
        """
        support: ReviewSupport = self._support
        prelude: Prelude = await support.prelude(action, RETRACT_COMMAND)
        if prelude.replay is not None:
            return result_from(prelude.replay, RetractResultDto)
        try:
            async with support.uow_factory() as uow:
                knowledge: Knowledge | None = await uow.knowledge.get_for_update(
                    action.record_id, space_id=prelude.space_id
                )
                if knowledge is None:
                    raise RecordNotFoundError(
                        f"No knowledge {action.record_id.value} in this space.",
                        {"record_id": action.record_id.value, "space_id": prelude.space_id.value},
                        next_steps=["Check the id and the active space."],
                    )
                raced: LedgerEntry | None = await support.raced(
                    uow, action, RETRACT_COMMAND, prelude
                )
                if raced is not None:
                    return result_from(raced, RetractResultDto)
                ReviewAuthorityPolicy.check(action.actor, [knowledge.applicability])
                proposal: bool = knowledge.status is RecordStatusEnum.PROPOSED
                basis = ReviewAuthorityPolicy.basis_for(action.actor)
                now = support.clock.now()
                decision: ReviewDecision = (
                    knowledge.reject(actor=action.actor, reason=action.reason, basis=basis, now=now)
                    if proposal
                    else knowledge.retract(
                        actor=action.actor, reason=action.reason, basis=basis, now=now
                    )
                )
                result: RetractResultDto = RetractResultDto(
                    id=knowledge.id.value,
                    status=knowledge.status.value,
                    outcome="rejected" if proposal else "retracted",
                    applied=action.apply,
                    decision_seq=decision.seq,
                    space_id=prelude.space_id.value,
                )
                if not action.apply:
                    return result
                changes: list[PendingRecordChange] = pending_changes_from(
                    knowledge.collect_events(),
                    record_type="knowledge",
                    status=knowledge.status.value,
                    occurred_at=now,
                    head_revision=knowledge.head_number,
                )
                await uow.knowledge.save(knowledge)
                await uow.ledger.record(
                    LedgerEntry(
                        space_id=prelude.space_id,
                        key=action.idempotency_key or "",
                        command=RETRACT_COMMAND,
                        fingerprint=prelude.fingerprint,
                        record_id=knowledge.id,
                        extra=result_extra(result),
                        recorded_at=now,
                    )
                )
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError as error:
            winner: LedgerEntry = await support.winner(error, action, RETRACT_COMMAND, prelude)
            return result_from(winner, RetractResultDto)
        return result
