"""Write repository of the Note aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.value_objects import NoteLocation


class INoteRepository(abc.ABC):
    """Loads and stores notes by location. No query methods: reads go through the read repository."""

    @abc.abstractmethod
    async def get(self, location: NoteLocation) -> Note | None:
        """The note at `location`, or None when there is none."""
        ...

    @abc.abstractmethod
    async def save(self, note: Note) -> None:
        """Stage `note` for writing; it becomes durable when the unit of work commits."""
        ...
