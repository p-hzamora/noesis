"""Write repository of the Source aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    RecordId,
    SourceKindEnum,
    SpaceId,
)


class ISourceRepository(abc.ABC):
    """Stores sources, which are write-once."""

    @abc.abstractmethod
    async def add(self, source: Source) -> None:
        """Stage a new source.

        Raises:
            EntryAlreadyExistsError: The id or the natural key is taken.
        """
        ...

    @abc.abstractmethod
    async def get(self, source_id: RecordId, *, space_id: SpaceId) -> Source | None:
        """The source with this id in `space_id`, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def get_by_natural_key(
        self,
        *,
        space_id: SpaceId,
        kind: SourceKindEnum,
        locator: str,
        digest: ContentHash | None,
    ) -> Source | None:
        """The source with this natural key, or None."""
        ...
