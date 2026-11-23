"""Live recommendation assertions, as Retrieval needs them."""

import abc
from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import AssertionSummaryContract


class IRecommendationReader(abc.ABC):
    """Read live recommendation assertions by evidence subjects."""

    @abc.abstractmethod
    async def by_subjects(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[AssertionSummaryContract]:
        """Live recommendation assertions whose subject is one of `ids`."""
        ...
