"""The decision history of a record (`review log`)."""

from noesis.bounded_context.knowledge.application.dtos import ReviewDecisionDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
    IReviewDecisionReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import require_space_id
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListReviewDecisionsQuery(FrozenObject):
    """Decisions of one record.

    Attributes:
        space_key: Key of the active space.
        record_id: The record.
    """

    space_key: Key
    record_id: RecordId


class ListReviewDecisionsHandler(IHandler[ListReviewDecisionsQuery, list[ReviewDecisionDto]]):
    """Thin read over `IReviewDecisionReadRepository.list_for`."""

    def __init__(
        self,
        *,
        read_repository: IReviewDecisionReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read_repository: IReviewDecisionReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: ListReviewDecisionsQuery) -> list[ReviewDecisionDto]:
        """Read the decisions, ordered by `seq`.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP)
        space_id = await require_space_id(self._records, action.space_key)
        return await self._read_repository.list_for(action.record_id, space_id=space_id)
