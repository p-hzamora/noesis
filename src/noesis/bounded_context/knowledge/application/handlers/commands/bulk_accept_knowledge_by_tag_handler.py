"""Accept every proposed Knowledge record that carries a tag, one unit of work per record."""

from noesis.bounded_context.knowledge.application.dtos import (
    BulkAcceptResultDto,
    TaggedProposalDto,
    TagMatchCountsDto,
)
from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewQueueReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.review_support import ReviewSupport
from noesis.bounded_context.knowledge.domain.entities import Knowledge, ReviewDecision
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    DecisionBasisEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    SpaceId,
    Tag,
)
from noesis.exceptions import AppException, ReviewNotAuthorisedError, StatusConflictError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

PAGE_SIZE: int = 100
SAMPLE_SIZE: int = 10
RERUN_HINT: str = "Rerun the same command; records already accepted are skipped."


class BulkAcceptKnowledgeByTagCommand(FrozenObject):
    """Accept the proposed Knowledge carrying a tag.

    Attributes:
        space_key: Key of the active space.
        actor: Who runs it; only a user may apply.
        tag: Tag matched exactly against the record's applicability tags.
        reason: Stored on every decision; `bulk accept: tag <tag>` when None.
        apply: False for a preview.
    """

    space_key: Key
    actor: Actor
    tag: Tag
    reason: str | None = None
    apply: bool = True


class BulkAcceptKnowledgeByTagHandler(
    IHandler[BulkAcceptKnowledgeByTagCommand, BulkAcceptResultDto]
):
    """Authority first, then counts, then a preview or paged one-record-per-transaction accepts."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        queue_reader: IReviewQueueReadRepository,
    ) -> None:
        self._support: ReviewSupport = ReviewSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._queue_reader: IReviewQueueReadRepository = queue_reader

    async def handle(self, action: BulkAcceptKnowledgeByTagCommand) -> BulkAcceptResultDto:
        """Preview or apply the bulk accept.

        Raises:
            ReviewNotAuthorisedError: Applying as an agent (`reason: bulk_accept_requires_user`),
                before any store is touched.
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            AppException: Any error that stops a run mid-way, with `accepted_before_failure` and
                `last_accepted_id` in its metadata and a rerun hint in its next steps.
        """
        if action.apply and not ReviewAuthorityPolicy.may_bulk_accept(action.actor):
            raise ReviewNotAuthorisedError(
                "Only the user may apply the bulk accept.",
                {"reason": "bulk_accept_requires_user"},
                next_steps=["Ask the user to run the command in their terminal."],
            )
        await self._support.require_schema()
        space_id: SpaceId = await self._support.references.resolve_space(action.space_key)
        counts: TagMatchCountsDto = await self._queue_reader.count_by_tag(space_id, action.tag)
        if not action.apply:
            sample: list[TaggedProposalDto] = await self._queue_reader.list_proposed_by_tag(
                space_id, action.tag, after_id=None, limit=SAMPLE_SIZE
            )
            return self._result(action, counts, accepted=0, skipped=0, sample=sample)
        accepted: list[TaggedProposalDto] = []
        skipped: int = 0
        after_id: RecordId | None = None
        try:
            while page := await self._queue_reader.list_proposed_by_tag(
                space_id, action.tag, after_id=after_id, limit=PAGE_SIZE
            ):
                for proposal in page:
                    if await self._accept_one(action, space_id, RecordId(value=proposal.id)):
                        accepted.append(proposal)
                    else:
                        skipped += 1
                after_id = RecordId(value=page[-1].id)
        except AppException as error:
            error.metadata["accepted_before_failure"] = len(accepted)
            error.metadata["last_accepted_id"] = accepted[-1].id if accepted else None
            error.next_steps = (*error.next_steps, RERUN_HINT)
            raise
        return self._result(
            action, counts, accepted=len(accepted), skipped=skipped, sample=accepted[:SAMPLE_SIZE]
        )

    async def _accept_one(
        self, action: BulkAcceptKnowledgeByTagCommand, space_id: SpaceId, record_id: RecordId
    ) -> bool:
        """Accept one record in its own unit of work; False when it changed before its turn."""
        support: ReviewSupport = self._support
        try:
            async with support.uow_factory() as uow:
                knowledge: Knowledge | None = await uow.knowledge.get_for_update(
                    record_id, space_id=space_id
                )
                if (
                    knowledge is None
                    or knowledge.status is not RecordStatusEnum.PROPOSED
                    or action.tag not in knowledge.applicability.tags
                ):
                    return False
                decision: ReviewDecision = knowledge.accept(
                    expected_revision=knowledge.head_number,
                    actor=action.actor,
                    reason=action.reason or f"bulk accept: tag {action.tag.value}",
                    basis=DecisionBasisEnum.MIGRATION,
                    now=support.clock.now(),
                )
                changes: list[PendingRecordChange] = pending_changes_from(
                    knowledge.collect_events(),
                    record_type="knowledge",
                    status=knowledge.status.value,
                    occurred_at=decision.decided_at,
                    head_revision=knowledge.head_number,
                )
                await uow.knowledge.save(knowledge)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except StatusConflictError:
            return False
        return True

    @staticmethod
    def _result(
        action: BulkAcceptKnowledgeByTagCommand,
        counts: TagMatchCountsDto,
        *,
        accepted: int,
        skipped: int,
        sample: list[TaggedProposalDto],
    ) -> BulkAcceptResultDto:
        return BulkAcceptResultDto(
            tag=action.tag.value,
            space=action.space_key.value,
            matched=counts.matched,
            proposed=counts.proposed,
            skipped_not_proposed=counts.matched - counts.proposed,
            accepted=accepted,
            skipped_changed=skipped,
            basis=DecisionBasisEnum.MIGRATION.value,
            sample=tuple(sample),
            applied=action.apply,
        )
