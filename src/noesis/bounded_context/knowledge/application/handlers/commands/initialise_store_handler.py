"""Apply the registered schema steps and ensure the default space."""

from noesis.bounded_context.knowledge.application.dtos import SpaceDto, StoreInitialisedDto
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.exceptions import EntryAlreadyExistsError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class InitialiseStoreCommand(FrozenObject):
    """Initialise the store.

    Attributes:
        default_space_key: Key of the configured default space.
        default_space_name: Display name when the space is created; the key when None.
    """

    default_space_key: Key
    default_space_name: str | None = None


class InitialiseStoreHandler(IHandler[InitialiseStoreCommand, StoreInitialisedDto]):
    """Applies each registered schema step once, then ensures the default space.

    Running it twice changes nothing the second time. There is no numeric schema version.
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._ids: IRecordIdGenerator = ids
        self._schema: IStoreSchema = schema

    async def handle(self, action: InitialiseStoreCommand) -> StoreInitialisedDto:
        """Apply the steps in registration order and ensure the default space."""
        applied: list[str] = []
        already: list[str] = []
        for name in self._schema.registered_steps():
            (applied if await self._schema.apply_step(name) else already).append(name)
        return StoreInitialisedDto(
            applied_steps=tuple(applied),
            already_applied_steps=tuple(already),
            default_space=await self._ensure_default_space(action),
        )

    async def _ensure_default_space(self, action: InitialiseStoreCommand) -> SpaceDto:
        try:
            async with self._uow_factory() as uow:
                found: KnowledgeSpace | None = await uow.spaces.get_by_key(action.default_space_key)
                if found is not None:
                    return _dto(found, created=False)
                space: KnowledgeSpace = KnowledgeSpace.create(
                    id=self._ids.new_space_id(),
                    key=action.default_space_key,
                    name=action.default_space_name or action.default_space_key.value,
                    now=self._clock.now(),
                )
                await uow.spaces.add(space)
                await uow.commit()
                return _dto(space, created=True)
        except EntryAlreadyExistsError:
            async with self._uow_factory() as uow:
                winner: KnowledgeSpace | None = await uow.spaces.get_by_key(
                    action.default_space_key
                )
            if winner is None:
                raise
            return _dto(winner, created=False)


def _dto(space: KnowledgeSpace, *, created: bool) -> SpaceDto:
    return SpaceDto(id=space.id.value, key=space.key.value, name=space.name, created=created)
