"""Write repository of the KnowledgeSpace aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key, SpaceId


class IKnowledgeSpaceRepository(abc.ABC):
    """Stores knowledge spaces."""

    @abc.abstractmethod
    async def add(self, space: KnowledgeSpace) -> None:
        """Stage a new space.

        Raises:
            EntryAlreadyExistsError: The id or key is taken.
        """
        ...

    @abc.abstractmethod
    async def get(self, space_id: SpaceId) -> KnowledgeSpace | None:
        """The space with this id, or None."""
        ...

    @abc.abstractmethod
    async def get_by_key(self, key: Key) -> KnowledgeSpace | None:
        """The space with this key, or None."""
        ...
