"""Write repository of the Note aggregate."""

import abc

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import NotePath


class INoteRepository(abc.ABC):
    """Loads and stores notes by path. No query methods: reads go through the read repository."""

    @abc.abstractmethod
    async def get(self, path: NotePath) -> Note | None:
        """The noesis note whose file is at `path`, or None when there is none."""
        ...

    @abc.abstractmethod
    async def exists(self, path: NotePath) -> bool:
        """Whether anything (a note, a plain file, a staged note) already occupies `path`."""
        ...

    @abc.abstractmethod
    async def save(self, note: Note) -> None:
        """Stage `note` for writing at its path; it becomes durable when the unit of work commits."""
        ...
