"""Apply the effect of an accepted `supersedes` assertion to its object (unit of work 2)."""

from datetime import datetime

from noesis.bounded_context.knowledge.application.dtos import EffectDto
from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.review_support import ReviewSupport
from noesis.bounded_context.knowledge.domain.entities import Assertion, Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import RecordNotFoundError, StatusConflictError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

OBJECT_NOT_ACCEPTED: str = "object_not_accepted"
CONCURRENT_DECISION: str = "concurrent_decision"
ASSERTION_NOT_ACCEPTED: str = "assertion_not_accepted"


class ApplySupersessionCommand(FrozenObject):
    """Run the effect of an accepted `supersedes` assertion.

    Attributes:
        space_key: Key of the active space.
        actor: Who runs the effect; named on the object's decision.
        assertion_id: The accepted `supersedes` assertion.
        object_id: Its object.
    """

    space_key: Key
    actor: Actor
    assertion_id: RecordId
    object_id: RecordId


class ApplySupersessionHandler(IHandler[ApplySupersessionCommand, EffectDto]):
    """Locks the object and, if it is still `accepted`, marks it `superseded`; convergent."""

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

    async def handle(self, action: ApplySupersessionCommand) -> EffectDto:
        """Apply the effect; running it again reports `applied` and writes nothing.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            RecordNotFoundError: The assertion or its object is unknown in the space.
        """
        support: ReviewSupport = self._support
        await support.require_schema()
        space_id = await support.references.resolve_space(action.space_key)

        def effect(outcome: str, reason: str | None = None) -> EffectDto:
            return EffectDto(
                record_id=action.object_id.value,
                outcome=outcome,
                reason=reason,
                assertion_id=action.assertion_id.value,
            )

        try:
            async with support.uow_factory() as uow:
                cause: Assertion | None = await uow.assertions.get_by_id(
                    action.assertion_id, space_id=space_id
                )
                if cause is None:
                    raise RecordNotFoundError(
                        f"No assertion {action.assertion_id.value} in this space.",
                        {"record_id": action.assertion_id.value, "space_id": space_id.value},
                        next_steps=["Check the id and the active space."],
                    )
                if cause.status is not RecordStatusEnum.ACCEPTED:
                    return effect("skipped", ASSERTION_NOT_ACCEPTED)
                knowledge: Knowledge | None = await uow.knowledge.get_for_update(
                    action.object_id, space_id=space_id
                )
                target: Knowledge | Assertion | None = (
                    knowledge
                    if knowledge is not None
                    else await uow.assertions.get_by_id(action.object_id, space_id=space_id)
                )
                if target is None:
                    raise RecordNotFoundError(
                        f"No record {action.object_id.value} in this space.",
                        {"record_id": action.object_id.value, "space_id": space_id.value},
                        next_steps=["Check the id and the active space."],
                    )
                if (
                    target.status is RecordStatusEnum.SUPERSEDED
                    and target.superseded_by_assertion_id == cause.id
                ):
                    return effect("applied")
                if target.status is not RecordStatusEnum.ACCEPTED:
                    return effect("skipped", OBJECT_NOT_ACCEPTED)
                now: datetime = support.clock.now()
                target.supersede(
                    cause=cause.id,
                    successor=cause.subject_id,
                    actor=action.actor,
                    now=now,
                )
                changes: list[PendingRecordChange] = pending_changes_from(
                    target.collect_events(),
                    record_type="knowledge" if isinstance(target, Knowledge) else "assertion",
                    status=target.status.value,
                    occurred_at=now,
                    head_revision=target.head_number if isinstance(target, Knowledge) else None,
                )
                if isinstance(target, Knowledge):
                    await uow.knowledge.save(target)
                else:
                    await uow.assertions.save(target)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except StatusConflictError:
            return effect("skipped", CONCURRENT_DECISION)
        return effect("applied")
