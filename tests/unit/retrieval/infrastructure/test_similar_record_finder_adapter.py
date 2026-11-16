"""SimilarRecordFinderAdapter maps the pipeline result to the kernel contract."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchHitDto,
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
    FindSimilarRecordsQuery,
)
from noesis.bounded_context.retrieval.domain.enums import (
    AuthorityTierEnum,
    CandidateKindEnum,
    ProjectScopeEnum,
    SemanticStateEnum,
)
from noesis.bounded_context.retrieval.infrastructure.inbound.knowledge.similar_record_finder_adapter import (
    SimilarRecordFinderAdapter,
)
from noesis.exceptions import IndexRebuildRequiredError
from noesis.shared_kernel.contracts.retrieval import SimilarRecordsContract

pytestmark = pytest.mark.unit


def hit(
    record_id: str,
    rank: int,
    sources: tuple[CandidateKindEnum, ...],
    revision: int | None = 2,
) -> RecordSearchHitDto:
    return RecordSearchHitDto(
        record_id=record_id,
        record_type="knowledge",
        subtype="decision",
        title="t",
        revision=revision,
        status="accepted",
        authority=AuthorityTierEnum.AUTHORITATIVE,
        project_id=None,
        sources=sources,
        revised_at=datetime(2026, 11, 14, tzinfo=UTC),
        rank=rank,
    )


def result(hits: tuple[RecordSearchHitDto, ...], state: SemanticStateEnum) -> RecordSearchResultDto:
    return RecordSearchResultDto(
        hits=hits,
        pending_changes=0,
        stale_hits=0,
        semantic_state=state,
        filter_shortfall=False,
        project_scope=ProjectScopeEnum.ALL_PROJECTS,
        project_id=None,
    )


def handler_returning(value: RecordSearchResultDto) -> AsyncMock:
    handler = AsyncMock(spec=FindSimilarRecordsHandler)
    handler.handle.return_value = value
    return handler


async def test_find_similar_maps_hits_state_and_leaves_similarity_null() -> None:
    handler = handler_returning(
        result(
            (
                hit("B", 1, (CandidateKindEnum.LEXICAL, CandidateKindEnum.SEMANTIC)),
                hit("C", 2, (CandidateKindEnum.GRAPH,), revision=None),
            ),
            SemanticStateEnum.LAGGING,
        )
    )

    contract = await SimilarRecordFinderAdapter(handler).find_similar("A", space_id="S", limit=7)

    assert isinstance(contract, SimilarRecordsContract)
    assert contract.contract_version == 1
    assert contract.anchor_id == "A"
    assert contract.semantic_state == "lagging"
    assert contract.similarity is None
    assert [(h.record_id, h.revision, h.rank, h.found_by) for h in contract.hits] == [
        ("B", 2, 1, ("lexical", "semantic")),
        ("C", None, 2, ("graph",)),
    ]
    handler.handle.assert_awaited_once_with(
        FindSimilarRecordsQuery(record_id="A", space_id="S", limit=7)
    )


@pytest.mark.parametrize("state", list(SemanticStateEnum))
async def test_find_similar_passes_every_semantic_state(state: SemanticStateEnum) -> None:
    contract = await SimilarRecordFinderAdapter(handler_returning(result((), state))).find_similar(
        "A", space_id="S", limit=1
    )

    assert contract.hits == ()
    assert contract.semantic_state == state.value


async def test_find_similar_lets_pipeline_errors_propagate_unchanged() -> None:
    handler = AsyncMock(spec=FindSimilarRecordsHandler)
    error = IndexRebuildRequiredError("rebuild", {})
    handler.handle.side_effect = error

    with pytest.raises(IndexRebuildRequiredError) as raised:
        await SimilarRecordFinderAdapter(handler).find_similar("A", space_id="S", limit=1)

    assert raised.value is error
