"""Persistence of the LinkSet aggregate, including the per-source write lock."""

import abc

from noesis.bounded_context.knowledge.domain.entities.link_set import LinkSet
from noesis.bounded_context.knowledge.domain.value_objects import RecordId


class ILinkSetRepository(abc.ABC):
    """All operations participate in the caller's unit of work."""

    @abc.abstractmethod
    async def get(self, source: RecordId) -> LinkSet | None:
        """Read without writing; absent labels require no schema special case."""
        ...

    @abc.abstractmethod
    async def lock(self, source: RecordId) -> None:
        """Create or lock the bookkeeping node before reading version and digest."""
        ...

    @abc.abstractmethod
    async def save(self, link_set: LinkSet) -> None:
        """Store metadata and diff this origin's edges in target id order."""
        ...
