"""How the consolidation scan reports a failed similarity lookup (spec 20-consolidation)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from noesis.bounded_context.knowledge.application.dtos import CandidateSnapshotDto
from noesis.bounded_context.knowledge.application.handlers.queries.scan_consolidation_candidates_handler import (
    ScanConsolidationCandidatesHandler,
)
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.exceptions import (
    AppException,
    GraphStoreUnavailableError,
    IndexRebuildRequiredError,
    SimilarityUnavailableError,
)
from noesis.shared_kernel.contracts.retrieval import SimilarRecordsContract

pytestmark = pytest.mark.unit

SPACE: SpaceId = SpaceId(value=f"{99:026d}")
ANCHOR_ID: str = f"{1:026d}"


def anchor() -> CandidateSnapshotDto:
    return CandidateSnapshotDto(
        record_id=ANCHOR_ID,
        record_type="knowledge",
        subtype="decision",
        tags=(),
        stored_status="accepted",
        effective_status="accepted",
        head_revision=1,
        title="t",
    )


def handler_with(finder: AsyncMock) -> ScanConsolidationCandidatesHandler:
    return ScanConsolidationCandidatesHandler(
        read_repository=MagicMock(), records=MagicMock(), schema=MagicMock(), finder=finder
    )


async def test_similar_returns_contract_unchanged() -> None:
    contract = SimilarRecordsContract(anchor_id=ANCHOR_ID, hits=(), semantic_state="ready")
    finder = AsyncMock()
    finder.find_similar.return_value = contract

    result = await handler_with(finder)._similar(anchor(), SPACE, 5)

    assert result is contract
    finder.find_similar.assert_awaited_once_with(ANCHOR_ID, space_id=SPACE.value, limit=5)


async def test_similar_preserves_integration_store_errors() -> None:
    error = GraphStoreUnavailableError("down", {})
    finder = AsyncMock()
    finder.find_similar.side_effect = error

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await handler_with(finder)._similar(anchor(), SPACE, 5)

    assert raised.value is error


async def test_similar_maps_other_errors_to_similarity_unavailable_with_original_code() -> None:
    error = IndexRebuildRequiredError("rebuild", {})
    finder = AsyncMock()
    finder.find_similar.side_effect = error

    with pytest.raises(SimilarityUnavailableError) as raised:
        await handler_with(finder)._similar(anchor(), SPACE, 5)

    assert raised.value.error_code == "KNOWLEDGE_190_SIMILARITY_UNAVAILABLE"
    assert raised.value.metadata == {"original_code": error.error_code, "anchor_id": ANCHOR_ID}
    assert raised.value.__cause__ is error
    assert isinstance(error, AppException)
