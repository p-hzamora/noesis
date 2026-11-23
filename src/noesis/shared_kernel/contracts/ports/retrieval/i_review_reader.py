"""Current effective review states, as Retrieval needs them."""

import abc
from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import RecordReviewStateContract


class IReviewReader(abc.ABC):
    """Read current effective review states in one space."""

    @abc.abstractmethod
    async def get_states(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[RecordReviewStateContract]:
        """Review states of the records `ids` in the space."""
        ...
