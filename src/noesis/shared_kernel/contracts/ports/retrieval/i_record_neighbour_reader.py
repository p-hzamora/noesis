"""Graph neighbours of seed records."""

import abc
from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import GraphNeighboursContract


class IRecordNeighbourReader(abc.ABC):
    """Records that share a Source with a seed."""

    @abc.abstractmethod
    async def neighbours(
        self, seed_ids: Sequence[str], *, space_id: str, limit: int
    ) -> GraphNeighboursContract:
        """One item per (neighbour, seed) pair; Knowledge and Experience records only."""
        ...
