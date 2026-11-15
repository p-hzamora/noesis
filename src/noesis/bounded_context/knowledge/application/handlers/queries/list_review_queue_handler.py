"""The review queue, with what the calling actor may decide."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import (
    ReviewQueueItemDto,
    ReviewQueuePageDto,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
    IReviewQueueReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import require_space_id
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.services import ReviewAuthorityPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordTypeEnum,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListReviewQueueQuery(FrozenObject):
    """A page of proposed records.

    Attributes:
        space_key: Key of the active space.
        actor: The caller; decides `decidable_by_caller`.
        project: List this project plus space-wide items.
        global_only: List only space-wide items.
        record_type: `knowledge` or `assertion`.
        predicate: Keep assertions with this predicate.
        limit: Page size.
        cursor: The previous page's `next_cursor`.
    """

    space_key: Key
    actor: Actor
    project: Key | None = None
    global_only: bool = False
    record_type: RecordTypeEnum | None = None
    predicate: AssertionPredicateEnum | None = None
    limit: int = Field(default=50, ge=1)
    cursor: str | None = None


class ListReviewQueueHandler(IHandler[ListReviewQueueQuery, ReviewQueuePageDto]):
    """Reads a page and fills `requires` and `decidable_by_caller` from the authority policy."""

    def __init__(
        self,
        *,
        read_repository: IReviewQueueReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read_repository: IReviewQueueReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: ListReviewQueueQuery) -> ReviewQueuePageDto:
        """Read the page.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP)
        space_id = await require_space_id(self._records, action.space_key)
        page: ReviewQueuePageDto = await self._read_repository.list_queue(
            space_id,
            project=action.project,
            global_only=action.global_only,
            record_type=action.record_type,
            predicate=action.predicate,
            limit=action.limit,
            cursor=action.cursor,
        )
        return page.model_copy(
            update={"items": tuple(self._with_decision(item, action.actor) for item in page.items)}
        )

    @staticmethod
    def _with_decision(item: ReviewQueueItemDto, actor: Actor) -> ReviewQueueItemDto:
        governing: list[Applicability] = [
            Applicability(project_id=RecordId(value=item.project_id) if item.project_id else None)
        ]
        return item.model_copy(
            update={
                "requires": ReviewAuthorityPolicy.requires(governing).value,
                "decidable_by_caller": ReviewAuthorityPolicy.may_decide(actor, governing),
            }
        )
