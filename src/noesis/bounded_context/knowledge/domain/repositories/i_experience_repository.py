"""Write repository of the Experience aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Experience
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId


class IExperienceRepository(abc.ABC):
    """Stores experiences, which are write-once."""

    @abc.abstractmethod
    async def add(self, experience: Experience) -> None:
        """Stage a new experience.

        Raises:
            EntryAlreadyExistsError: The id is taken.
        """
        ...

    @abc.abstractmethod
    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Experience | None:
        """The experience with this id in `space_id`, or None (also when it is in another space)."""
        ...
