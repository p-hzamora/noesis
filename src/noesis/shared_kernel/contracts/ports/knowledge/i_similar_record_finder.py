"""Similar-records lookup port, answered by Retrieval's shared search pipeline."""

import abc

from noesis.shared_kernel.contracts.retrieval import SimilarRecordsContract


class ISimilarRecordFinder(abc.ABC):
    """Finds records near an anchor record.

    Retrieval's inbound adapter inherits this interface; Knowledge imports nothing from
    Retrieval, only the kernel.
    """

    @abc.abstractmethod
    async def find_similar(
        self, record_id: str, *, space_id: str, limit: int
    ) -> SimilarRecordsContract:
        """Records near `record_id` in `space_id`, in rank order, unfiltered by status or project.

        Args:
            record_id: The anchor.
            space_id: The active space.
            limit: At most this many hits.

        Returns:
            The hits and the semantic state; `similarity` is always null.
        """
        ...
