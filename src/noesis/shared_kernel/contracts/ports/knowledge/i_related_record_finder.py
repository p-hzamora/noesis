"""Related-record lookup port, answered by Retrieval's text search."""

import abc

from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract


class IRelatedRecordFinder(abc.ABC):
    """Finds records on the same topic as a text.

    Retrieval's inbound adapter inherits this interface; Knowledge imports nothing from
    Retrieval (D17), only the kernel.
    """

    @abc.abstractmethod
    async def find(
        self, text: str, *, space_id: str, project_key: str | None, limit: int
    ) -> RecordSearchHitContract:
        """Search `space_id` for records related to `text`, the project's and space-wide ones.

        Args:
            text: What to look for.
            space_id: The active space.
            project_key: The brief's project.
            limit: At most this many hits.

        Returns:
            The hits and the index lag (`pending_changes`).
        """
        ...
