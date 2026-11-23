"""Read side of assertions."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import AssertionDto, AssertionSummaryDto
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    AssertionRoleEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)


class IAssertionReadRepository(abc.ABC):
    """Assertions as DTOs."""

    @abc.abstractmethod
    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> AssertionDto | None:
        """The assertion, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def list_about(
        self,
        record_id: RecordId,
        *,
        space_id: SpaceId,
        role: AssertionRoleEnum,
        statuses: Sequence[RecordStatusEnum],
        predicates: Sequence[AssertionPredicateEnum],
    ) -> list[AssertionDto]:
        """Assertions in which the record plays `role`; empty filters match all."""
        ...

    @abc.abstractmethod
    async def list_by_subjects(
        self,
        subject_ids: Sequence[RecordId],
        *,
        space_id: SpaceId,
        predicates: Sequence[AssertionPredicateEnum],
        statuses: Sequence[RecordStatusEnum],
    ) -> list[AssertionSummaryDto]:
        """Summaries of the assertions whose subject is in `subject_ids`, ascending id."""
        ...

    @abc.abstractmethod
    async def list_by_objects(
        self,
        object_ids: Sequence[RecordId],
        *,
        space_id: SpaceId,
        predicates: Sequence[AssertionPredicateEnum],
        statuses: Sequence[RecordStatusEnum],
    ) -> list[AssertionSummaryDto]:
        """Summaries of the assertions whose object is in `object_ids`, ascending id."""
        ...
