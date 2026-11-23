"""The similar-records lookup Knowledge's consolidation scan asks for, answered by `RecordSearcher`.

Structurally matches Knowledge's `ISimilarRecordFinder`; Retrieval imports nothing from Knowledge.
"""

from noesis.shared_kernel.contracts.ports.knowledge import ISimilarRecordFinder
from noesis.shared_kernel.contracts.retrieval import SimilarRecordHitItem, SimilarRecordsContract

from ....application.dtos.record_search_dtos import RecordSearchHitDto
from ....application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
    FindSimilarRecordsQuery,
)


class SimilarRecordFinderAdapter(ISimilarRecordFinder):
    """Runs the shared pipeline for an anchor and returns the kernel contract.

    Errors of the pipeline propagate unchanged; the caller decides how to report them.
    """

    def __init__(self, handler: FindSimilarRecordsHandler) -> None:
        self._handler: FindSimilarRecordsHandler = handler

    async def find_similar(
        self, record_id: str, *, space_id: str, limit: int
    ) -> SimilarRecordsContract:
        """Records near `record_id` in `space_id`, unfiltered by status or project."""
        result = await self._handler.handle(
            FindSimilarRecordsQuery(record_id=record_id, space_id=space_id, limit=limit)
        )
        return SimilarRecordsContract(
            anchor_id=record_id,
            hits=tuple(_item(hit) for hit in result.hits),
            semantic_state=result.semantic_state.value,
        )


def _item(hit: RecordSearchHitDto) -> SimilarRecordHitItem:
    return SimilarRecordHitItem(
        record_id=hit.record_id,
        revision=hit.revision,
        rank=hit.rank,
        found_by=tuple(kind.value for kind in hit.sources),
    )
