"""Write repository of the Project aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Project
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId


class IProjectRepository(abc.ABC):
    """Stores projects."""

    @abc.abstractmethod
    async def add(self, project: Project) -> None:
        """Stage a new project.

        Raises:
            EntryAlreadyExistsError: The id is taken, or the key is taken in the space.
        """
        ...

    @abc.abstractmethod
    async def get(self, project_id: RecordId, *, space_id: SpaceId) -> Project | None:
        """The project with this id in `space_id`, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def get_by_key(self, key: Key, *, space_id: SpaceId) -> Project | None:
        """The project with this key in `space_id`, or None."""
        ...
