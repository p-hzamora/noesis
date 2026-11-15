"""Read side of the catalog: DTOs, never aggregates."""

import abc

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDetailDto,
    CatalogEntryDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    RecordId,
    SpaceId,
)


class ICatalogEntryReadRepository(abc.ABC):
    """Reads catalog entries of one space; another space's entry reads as None."""

    @abc.abstractmethod
    async def get_by_id(
        self, record_id: RecordId, *, space_id: SpaceId, revision: int | None = None
    ) -> CatalogEntryDetailDto | None:
        """The entry with the requested revision (the head by default), or None.

        None also when the entry has no such revision.
        """
        ...

    @abc.abstractmethod
    async def get_by_key(
        self,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: str,
        *,
        revision: int | None = None,
    ) -> CatalogEntryDetailDto | None:
        """Like `get_by_id`, found by kind and exact name."""
        ...

    @abc.abstractmethod
    async def find(
        self,
        space_id: SpaceId,
        *,
        kind: CatalogEntryKindEnum | None = None,
        name_prefix: str | None = None,
    ) -> tuple[CatalogEntryDto, ...]:
        """Entries of `space_id`, optionally narrowed by kind and by name prefix (case-sensitive)."""
        ...
