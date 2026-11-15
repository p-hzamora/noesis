"""Read side of review decisions."""

import abc

from noesis.bounded_context.knowledge.application.dtos import ReviewDecisionDto
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId


class IReviewDecisionReadRepository(abc.ABC):
    """The decision history of a record."""

    @abc.abstractmethod
    async def list_for(self, record_id: RecordId, *, space_id: SpaceId) -> list[ReviewDecisionDto]:
        """Decisions of the record ordered by `seq`; empty when none or unknown."""
        ...
