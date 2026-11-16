"""The related-record lookup Knowledge's curation asks for, answered by `RecordSearcher`.

Structurally matches Knowledge's `IRelatedRecordFinder`; Retrieval imports nothing from Knowledge.
"""

from datetime import UTC, datetime

from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract, RecordSearchHitItem

from ....application.dtos.record_search_dtos import RecordSearchHitDto, RecordSearchRequestDto
from ....application.services.record_searcher import RecordSearcher


class RelatedRecordFinderAdapter:
    """Searches the space for records related to a text and returns the kernel contract."""

    def __init__(self, searcher: RecordSearcher) -> None:
        self._searcher: RecordSearcher = searcher

    async def find(
        self, text: str, *, space_id: str, project_key: str | None, limit: int
    ) -> RecordSearchHitContract:
        """Search with no tag, type or status filter (retracted records are excluded).

        Errors of the searcher propagate unchanged.
        """
        result = await self._searcher.search(
            RecordSearchRequestDto(
                text=text,
                space_id=space_id,
                project_key=project_key,
                all_projects=False,
                limit=limit,
            )
        )
        return RecordSearchHitContract(
            hits=tuple(_item(hit) for hit in result.hits),
            pending_changes=result.pending_changes,
            semantic_state=result.semantic_state.value,
        )


def _item(hit: RecordSearchHitDto) -> RecordSearchHitItem:
    return RecordSearchHitItem(
        record_id=hit.record_id,
        record_type=hit.record_type,
        subtype=hit.subtype,
        title=hit.title,
        revision=hit.revision,
        status=hit.status,
        authority=hit.authority.value,
        project_id=hit.project_id,
        sources=tuple(kind.value for kind in hit.sources),
        revised_at=_iso_utc(hit.revised_at),
        rank=hit.rank,
    )


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
