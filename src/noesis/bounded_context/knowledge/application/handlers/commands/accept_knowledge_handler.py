"""Accept proposed Knowledge, pinning the head revision the reviewer judged."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import AcceptResultDto
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
from noesis.bounded_context.knowledge.domain.entities import Knowledge, ReviewDecision
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import RecordId
from noesis.exceptions import (
    EntryAlreadyExistsError,
    ExpectedRevisionRequiredError,
    RecordNotFoundError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock

ACCEPT_COMMAND: str = "review.accept"


class AcceptKnowledgeCommand(ReviewMutationCommand):
    """Accept one Knowledge record.

    Attributes:
        record_id: The knowledge to accept.
        expected_revision: The head the reviewer judged; required.
        reason: Why, when given.
    """

    record_id: RecordId
    expected_revision: int | None = Field(default=None, ge=1)
    reason: str | None = None


class AcceptKnowledgeHandler(IHandler[AcceptKnowledgeCommand, AcceptResultDto]):
    """Locks the record, checks authority, lifecycle and head, then records the decision."""

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

    async def handle(self, action: AcceptKnowledgeCommand) -> AcceptResultDto:
        """Accept, preview, or replay the earlier identical accept.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            RecordNotFoundError: No such knowledge in the space.
            ExpectedRevisionRequiredError: No expected revision given.
            ReviewNotAuthorisedError: The actor may not decide this scope.
            InvalidStatusTransitionError: The knowledge is not `proposed`.
            RevisionConflictError: The expected revision is not the head.
            StatusConflictError: A concurrent decision won.
        """
        support: ReviewSupport = self._support
        prelude: Prelude = await support.prelude(action, ACCEPT_COMMAND)
        if prelude.replay is not None:
            return result_from(prelude.replay, AcceptResultDto)
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
                    uow, action, ACCEPT_COMMAND, prelude
                )
                if raced is not None:
                    return result_from(raced, AcceptResultDto)
                if action.expected_revision is None:
                    raise ExpectedRevisionRequiredError(
                        "Accepting knowledge needs the head revision you judged.",
                        {"record_id": action.record_id.value},
                        next_steps=["Run `noesis record get`, then pass the head revision."],
                    )
                ReviewAuthorityPolicy.check(action.actor, [knowledge.applicability])
                decision: ReviewDecision = knowledge.accept(
                    expected_revision=action.expected_revision,
                    actor=action.actor,
                    reason=action.reason,
                    basis=ReviewAuthorityPolicy.basis_for(action.actor),
                    now=support.clock.now(),
                )
                result: AcceptResultDto = AcceptResultDto(
                    id=knowledge.id.value,
                    type="knowledge",
                    status=knowledge.status.value,
                    pinned_revision=decision.pinned_revision,
                    decision_seq=decision.seq,
                    basis=decision.basis.value,
                    applied=action.apply,
                    space_id=prelude.space_id.value,
                )
                if not action.apply:
                    return result
                await uow.knowledge.save(knowledge)
                await uow.ledger.record(
                    LedgerEntry(
                        space_id=prelude.space_id,
                        key=action.idempotency_key or "",
                        command=ACCEPT_COMMAND,
                        fingerprint=prelude.fingerprint,
                        record_id=knowledge.id,
                        revision=decision.pinned_revision,
                        extra=result_extra(result),
                        recorded_at=decision.decided_at,
                    )
                )
                await uow.commit()
        except EntryAlreadyExistsError as error:
            winner: LedgerEntry = await support.winner(error, action, ACCEPT_COMMAND, prelude)
            return result_from(winner, AcceptResultDto)
        return result
