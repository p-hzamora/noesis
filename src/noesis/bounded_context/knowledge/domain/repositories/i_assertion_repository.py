"""Write repository of the Assertion aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities import Assertion
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId, StatementKey


class IAssertionRepository(abc.ABC):
    """Stores assertions and their review state."""

    @abc.abstractmethod
    async def add(self, assertion: Assertion) -> None:
        """Stage a new assertion.

        Raises:
            EntryAlreadyExistsError: The id is taken.
            DuplicateAssertionError: A live identical statement exists (storage backstop).
        """
        ...

    @abc.abstractmethod
    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> Assertion | None:
        """The assertion with this id in `space_id`, or None (also when it is in another space)."""
        ...

    @abc.abstractmethod
    async def get_live_by_statement(self, key: StatementKey) -> Assertion | None:
        """The `proposed` or `accepted` assertion stating `key`, or None."""
        ...

    @abc.abstractmethod
    async def save(self, assertion: Assertion) -> None:
        """Stage the assertion's status, `decision_seq` and latest decision.

        Raises:
            StatusConflictError: Another decision with the same decision key won.
        """
        ...
