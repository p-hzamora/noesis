"""Find the records most like an anchor record."""

from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

from ...dtos.record_search_dtos import RecordSearchResultDto
from ...services.record_searcher import RecordSearcher


class FindSimilarRecordsQuery(FrozenObject):
    """Records similar to an anchor.

    Attributes:
        record_id: The anchor.
        space_id: The active space.
        limit: Most hits returned.
    """

    record_id: str
    space_id: str
    limit: int


class FindSimilarRecordsHandler(IHandler[FindSimilarRecordsQuery, RecordSearchResultDto]):
    """Delegates to `RecordSearcher.similar`."""

    def __init__(self, searcher: RecordSearcher) -> None:
        self._searcher: RecordSearcher = searcher

    async def handle(self, action: FindSimilarRecordsQuery) -> RecordSearchResultDto:
        """Find similar records; an anchor outside the space gives no hits."""
        return await self._searcher.similar(
            action.record_id, space_id=action.space_id, limit=action.limit
        )
