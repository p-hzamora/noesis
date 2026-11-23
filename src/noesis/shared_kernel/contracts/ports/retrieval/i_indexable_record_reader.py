"""The only path by which a record body reaches Retrieval."""

import abc

from noesis.shared_kernel.contracts.knowledge import IndexableRecordContract, RecordBodyMissingError

__all__ = ["IIndexableRecordReader", "RecordBodyMissingError"]


class IIndexableRecordReader(abc.ABC):
    """Reads one record revision with its text."""

    @abc.abstractmethod
    async def get(
        self, record_id: str, revision: int | None, *, space_id: str
    ) -> IndexableRecordContract:
        """The record at `revision` (null for types without revisions).

        Raises:
            RecordBodyMissingError: The revision has no body, so it cannot be indexed.
        """
        ...
