"""Write repository of the CatalogEntry aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogRevision,
    RecordId,
    SpaceId,
)


class ICatalogEntryRepository(abc.ABC):
    """Stores catalog entries and their revisions."""

    @abc.abstractmethod
    async def add(self, entry: CatalogEntry) -> None:
        """Stage a new entry with its revision 1.

        Raises:
            CatalogEntryAlreadyExistsError: The kind and name exist in the space.
            EntryAlreadyExistsError: The id is taken.
        """
        ...

    @abc.abstractmethod
    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> CatalogEntry | None:
        """The entry with this id in `space_id`, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def get_by_key(
        self, space_id: SpaceId, kind: CatalogEntryKindEnum, name: str
    ) -> CatalogEntry | None:
        """The entry with this kind and exact name in `space_id`, or None."""
        ...

    @abc.abstractmethod
    async def get_for_update(
        self, record_id: RecordId, *, space_id: SpaceId
    ) -> CatalogEntry | None:
        """Like `get`, but locks the entry until the unit of work ends (A-13)."""
        ...

    @abc.abstractmethod
    async def append_revision(self, entry: CatalogEntry, revision: CatalogRevision) -> None:
        """Stage `revision` as the new head of `entry`.

        Raises:
            RevisionConflictError: Revision `revision.number` already exists; the metadata has
                the expected and actual head.
        """
        ...
