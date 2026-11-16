"""Graph neighbours of seed records."""

from collections.abc import Sequence
from typing import Protocol

from noesis.shared_kernel.contracts.knowledge import GraphNeighbourContract


class IRecordNeighbourReader(Protocol):
    """Records that share a Source with a seed."""

    async def neighbours(
        self, seed_ids: Sequence[str], *, space_id: str, limit: int
    ) -> list[GraphNeighbourContract]:
        """One item per (neighbour, seed) pair; Knowledge and Experience records only."""
        ...
