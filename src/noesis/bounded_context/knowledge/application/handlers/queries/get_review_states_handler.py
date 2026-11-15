"""Review states of records, for the CLI dispatch and for Retrieval's inbound adapter."""

from noesis.bounded_context.knowledge.application.dtos import ReviewStateDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
    IReviewStateReadRepository,
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


class GetReviewStatesQuery(FrozenObject):
    """Review states of the given records.

    Attributes:
        space_key: Key of the active space.
        record_ids: The records.
    """

    space_key: Key
    record_ids: tuple[RecordId, ...]


class GetReviewStatesHandler(IHandler[GetReviewStatesQuery, list[ReviewStateDto]]):
    """One state per known id, in the order given; unknown ids are left out."""

    def __init__(
        self,
        *,
        read_repository: IReviewStateReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read_repository: IReviewStateReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: GetReviewStatesQuery) -> list[ReviewStateDto]:
        """Read the states.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP)
        space_id = await require_space_id(self._records, action.space_key)
        return await self._read_repository.get_states(action.record_ids, space_id)
