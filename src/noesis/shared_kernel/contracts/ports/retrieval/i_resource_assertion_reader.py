"""Live assertions that point at resources, as Retrieval needs them."""

import abc
from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import AssertionSummaryContract


class IResourceAssertionReader(abc.ABC):
    """Read live assertions that point at resources (recommendations, refinements)."""

    @abc.abstractmethod
    async def by_objects(
        self, ids: Sequence[str], *, space_id: str, predicates: Sequence[str]
    ) -> list[AssertionSummaryContract]:
        """Live assertions with one of `predicates` whose object is one of `ids`."""
        ...
