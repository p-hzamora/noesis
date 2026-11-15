"""Write repository of the Knowledge aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, Revision, SpaceId


class IKnowledgeRepository(abc.ABC):
    """Stores knowledge records and their revisions."""

    @abc.abstractmethod
    async def add(self, knowledge: Knowledge) -> None:
        """Stage new knowledge with its revision 1.

        Raises:
            EntryAlreadyExistsError: The id is taken.
        """
        ...

    @abc.abstractmethod
    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        """The knowledge with this id in `space_id`, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def get_for_update(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        """Like `get`, but locks the record until the unit of work ends.

        A concurrent `get_for_update` of the same record waits, so status and head are checked
        in order (A-13).
        """
        ...

    @abc.abstractmethod
    async def append_revision(self, knowledge: Knowledge, revision: Revision) -> None:
        """Stage `revision` as the new head of `knowledge`.

        Raises:
            RevisionConflictError: Revision `revision.number` already exists; the metadata has
                the expected and actual head.
        """
        ...

    @abc.abstractmethod
    async def save(self, knowledge: Knowledge) -> None:
        """Stage the record's status, `decision_seq`, `superseded_by_assertion_id` and latest decision.

        Raises:
            StatusConflictError: Another decision with the same decision key won.
        """
        ...
