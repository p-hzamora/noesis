"""Read side of derived review states."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import PendingEffectDto, ReviewStateDto
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId


class IReviewStateReadRepository(abc.ABC):
    """Review states, with `authority` decided by the domain functions."""

    @abc.abstractmethod
    async def get_states(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[ReviewStateDto]:
        """One state per id known in the space, in the order given."""
        ...

    @abc.abstractmethod
    async def list_pending_effects(self, space_id: SpaceId) -> list[PendingEffectDto]:
        """Accepted `supersedes` assertions whose object's stored status is still `accepted`."""
        ...
