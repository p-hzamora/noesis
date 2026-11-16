"""Search the records of the active space."""

from noesis.shared_kernel.application.handlers import IHandler

from ...dtos.record_search_dtos import RecordSearchRequestDto, RecordSearchResultDto
from ...services.record_searcher import RecordSearcher


class SearchRecordsHandler(IHandler[RecordSearchRequestDto, RecordSearchResultDto]):
    """Delegates to `RecordSearcher`; repeats no pipeline step."""

    def __init__(self, searcher: RecordSearcher) -> None:
        self._searcher: RecordSearcher = searcher

    async def handle(self, action: RecordSearchRequestDto) -> RecordSearchResultDto:
        """Search.

        Raises:
            IndexRebuildRequiredError: The semantic profile changed.
            SemanticIndexUnavailableError: Semantic search was required and is not usable.
        """
        return await self._searcher.search(action)
