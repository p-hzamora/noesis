"""Knowledge's full-text search: the only lexical source."""

import abc

from noesis.shared_kernel.contracts.knowledge import RecordHitContract


class IRecordTextSearch(abc.ABC):
    """Full-text search over head revisions and Experience bodies."""

    @abc.abstractmethod
    async def search(self, text: str, *, space_id: str, limit: int) -> list[RecordHitContract]:
        """Up to `limit` hits of the space, best first, ranks 1..n."""
        ...
