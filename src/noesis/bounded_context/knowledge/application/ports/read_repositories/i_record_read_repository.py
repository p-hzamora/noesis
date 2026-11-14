"""Read side of the record store: DTOs, never aggregates."""

import abc

from noesis.bounded_context.knowledge.application.dtos import RecordDto, RevisionDto
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId


class IRecordReadRepository(abc.ABC):
    """Reads any persisted record by id within one space."""

    @abc.abstractmethod
    async def get_space_id(self, key: Key) -> SpaceId | None:
        """Id of the space with this key, or None."""
        ...

    @abc.abstractmethod
    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> RecordDto | None:
        """The record with its head revision (knowledge), or None.

        A record of another space is None, exactly like an unknown id.
        """
        ...

    @abc.abstractmethod
    async def get_revision(
        self, record_id: RecordId, number: int, *, space_id: SpaceId
    ) -> RevisionDto | None:
        """Revision `number` of a Knowledge record in `space_id`, or None."""
        ...
