"""Related-record lookup port, answered by Retrieval's text search."""

from typing import Protocol

from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract


class IRelatedRecordFinder(Protocol):
    """Finds records on the same topic as a text.

    A structural port: Retrieval's inbound adapter satisfies it without importing Knowledge, and
    Knowledge imports nothing from Retrieval (D17), only the kernel contract.
    """

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
