"""Ranked search over a vector index of the notes."""

import abc

from noesis.bounded_context.notes.application.dtos import VectorHitDto


class IVectorSearch(abc.ABC):
    """A derived, rebuildable index. No vendor assumptions: ids, paths and ranks only."""

    @abc.abstractmethod
    async def search(self, query: str, k: int) -> tuple[VectorHitDto, ...]:
        """The `k` best matches, best first.

        Args:
            query: Free-text query.
            k: Most hits to return.
        """
        ...
