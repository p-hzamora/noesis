"""Assertion summaries by subject, for Retrieval's inbound adapter (batch)."""

from noesis.bounded_context.knowledge.application.dtos import AssertionSummaryDto
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
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ListAssertionsBySubjectsQuery(FrozenObject):
    """Assertions whose subject is one of the given records.

    Attributes:
        space_key: Key of the active space.
        subject_ids: The subjects.
        predicates: Predicates to keep; empty keeps all.
        statuses: Stored statuses to keep; empty keeps all.
    """

    space_key: Key
    subject_ids: tuple[RecordId, ...]
    predicates: tuple[AssertionPredicateEnum, ...] = ()
    statuses: tuple[RecordStatusEnum, ...] = ()


class ListAssertionsBySubjectsHandler(
    IHandler[ListAssertionsBySubjectsQuery, list[AssertionSummaryDto]]
):
    """Summaries in ascending assertion id."""

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

    async def handle(self, action: ListAssertionsBySubjectsQuery) -> list[AssertionSummaryDto]:
        """Read the summaries.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP)
        space_id = await require_space_id(self._records, action.space_key)
        if not action.subject_ids:
            return []
        return await self._read_repository.list_by_subjects(
            action.subject_ids,
            space_id=space_id,
            predicates=action.predicates,
            statuses=action.statuses,
        )
