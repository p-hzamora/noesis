"""Pull access to Knowledge's change feed."""

import abc

from noesis.shared_kernel.contracts.knowledge import RecordChangedContract


class IRecordChangeFeed(abc.ABC):
    """The ordered record changes of a space."""

    @abc.abstractmethod
    async def changes_after(
        self, sequence: int, *, space_id: str, limit: int
    ) -> list[RecordChangedContract]:
        """Changes of the space with a sequence above `sequence`, ascending, at most `limit`."""
        ...

    @abc.abstractmethod
    async def head_sequence(self, space_id: str) -> int:
        """The highest sequence of the space; 0 when no change exists."""
        ...
