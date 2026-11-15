"""`review repair`: run the supersession effect of every accepted `supersedes` still pending."""

from noesis.bounded_context.knowledge.application.dtos import EffectDto, RepairResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionCommand,
    ApplySupersessionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import ReviewSupport
from noesis.bounded_context.knowledge.domain.value_objects import Actor, Key, RecordId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class RepairSupersessionEffectsCommand(FrozenObject):
    """Repair pending supersession effects.

    Attributes:
        space_key: Key of the active space.
        actor: Who runs the effects; named on each object's decision.
        apply: False for a preview: list what would be applied and write nothing.
    """

    space_key: Key
    actor: Actor
    apply: bool = True


class RepairSupersessionEffectsHandler(IHandler[RepairSupersessionEffectsCommand, RepairResultDto]):
    """Pending is derived from state; each effect is its own unit of work and takes no key."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        state_reader: IReviewStateReadRepository,
    ) -> None:
        self._support: ReviewSupport = ReviewSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._effect: ApplySupersessionHandler = ApplySupersessionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._state_reader: IReviewStateReadRepository = state_reader

    async def handle(self, action: RepairSupersessionEffectsCommand) -> RepairResultDto:
        """Apply (or, in a preview, list) every pending effect.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await self._support.require_schema()
        space_id = await self._support.references.resolve_space(action.space_key)
        pending = await self._state_reader.list_pending_effects(space_id)
        effects: list[EffectDto] = []
        for item in pending:
            if not action.apply:
                effects.append(
                    EffectDto(
                        record_id=item.object_id, outcome="applied", assertion_id=item.assertion_id
                    )
                )
                continue
            effects.append(
                await self._effect.handle(
                    ApplySupersessionCommand(
                        space_key=action.space_key,
                        actor=action.actor,
                        assertion_id=RecordId(value=item.assertion_id),
                        object_id=RecordId(value=item.object_id),
                    )
                )
            )
        return RepairResultDto(effects=tuple(effects), applied=action.apply)
