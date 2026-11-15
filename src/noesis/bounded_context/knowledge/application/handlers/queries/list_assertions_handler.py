"""Assertions about a record, by the part it plays."""

from noesis.bounded_context.knowledge.application.dtos import AssertionDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IAssertionReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import require_space_id
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    AssertionRoleEnum,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListAssertionsQuery(FrozenObject):
    """Assertions in which a record plays a part.

    Attributes:
        space_key: Key of the active space.
        record_id: The record.
        role: The part it plays; `any` by default.
        predicates: Predicates to keep; empty keeps all.
        statuses: Stored statuses to keep; empty keeps all.
    """

    space_key: Key
    record_id: RecordId
    role: AssertionRoleEnum = AssertionRoleEnum.ANY
    predicates: tuple[AssertionPredicateEnum, ...] = ()
    statuses: tuple[RecordStatusEnum, ...] = ()


class ListAssertionsHandler(IHandler[ListAssertionsQuery, list[AssertionDto]]):
    """Thin read over `IAssertionReadRepository.list_about`."""

    def __init__(
        self,
        *,
        read_repository: IAssertionReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read_repository: IAssertionReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: ListAssertionsQuery) -> list[AssertionDto]:
        """Read the assertions.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP)
        space_id = await require_space_id(self._records, action.space_key)
        return await self._read_repository.list_about(
            action.record_id,
            space_id=space_id,
            role=action.role,
            statuses=action.statuses,
            predicates=action.predicates,
        )
