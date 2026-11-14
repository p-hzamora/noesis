"""Source of new ids."""

import abc

from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId


class IRecordIdGenerator(abc.ABC):
    """Hands out ULIDs for records and spaces about to be created."""

    @abc.abstractmethod
    def new_record_id(self) -> RecordId:
        """A new, unique record id."""
        ...

    @abc.abstractmethod
    def new_space_id(self) -> SpaceId:
        """A new, unique space id."""
        ...
