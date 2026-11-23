"""Current state of records, as Retrieval needs it to resolve, filter and rank."""

import abc
from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import RecordStateContract


class IRecordStateReader(abc.ABC):
    """Reads record states and resolves project keys."""

    @abc.abstractmethod
    async def get_states(
        self, record_ids: Sequence[str], *, space_id: str
    ) -> list[RecordStateContract]:
        """States of the records found in the space; ids not found are omitted."""
        ...

    @abc.abstractmethod
    async def scan_states(
        self, space_id: str, *, after_id: str | None, limit: int
    ) -> list[RecordStateContract]:
        """A page of the space's record states ordered by record id, after `after_id`."""
        ...

    @abc.abstractmethod
    async def find_project_id(self, project_key: str, *, space_id: str) -> str | None:
        """The id of the project with this key in the space, else None."""
        ...
