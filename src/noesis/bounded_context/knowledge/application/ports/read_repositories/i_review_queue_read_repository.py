"""Read side of the review queue and the tag selection of the bulk accept."""

import abc

from noesis.bounded_context.knowledge.application.dtos import (
    ReviewQueuePageDto,
    TaggedProposalDto,
    TagMatchCountsDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordTypeEnum,
    SpaceId,
    Tag,
)


class IReviewQueueReadRepository(abc.ABC):
    """Queue pages and tag counts, as DTOs."""

    @abc.abstractmethod
    async def list_queue(
        self,
        space_id: SpaceId,
        *,
        project: Key | None,
        global_only: bool,
        record_type: RecordTypeEnum | None,
        predicate: AssertionPredicateEnum | None,
        limit: int,
        cursor: str | None,
    ) -> ReviewQueuePageDto:
        """Records with effective status `proposed`, ascending id.

        `project` lists that project plus space-wide items; `global_only` only space-wide ones.
        `requires` and `decidable_by_caller` are left unset for the handler to fill.
        """
        ...

    @abc.abstractmethod
    async def count_by_tag(self, space_id: SpaceId, tag: Tag) -> TagMatchCountsDto:
        """Knowledge carrying `tag` (any status) and how many of them are stored `proposed`."""
        ...

    @abc.abstractmethod
    async def list_proposed_by_tag(
        self, space_id: SpaceId, tag: Tag, *, after_id: RecordId | None, limit: int
    ) -> list[TaggedProposalDto]:
        """Proposed Knowledge carrying `tag`, ascending id, with ids greater than `after_id`."""
        ...
