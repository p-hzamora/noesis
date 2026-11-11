"""Source of new note ids."""

import abc

from noesis.bounded_context.notes.domain.value_objects import NoteId


class INoteIdGenerator(abc.ABC):
    """Hands out ids for notes that are about to be created."""

    @abc.abstractmethod
    def new_id(self) -> NoteId:
        """A new, unique id."""
        ...
