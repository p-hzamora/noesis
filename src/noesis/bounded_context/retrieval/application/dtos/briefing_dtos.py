"""Recall's read evidence, grounded sections and independently observed tools."""

from typing import Literal

from pydantic import Field

from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    CatalogAvailabilityRuntimeContract,
    GraphNeighbourContract,
)
from noesis.utils import FrozenObject

from .record_search_dtos import RecordSearchRequestDto, RecordSearchResultDto


class RecallRequestDto(FrozenObject):
    """One scoped briefing request; digest does not require a model."""

    search: RecordSearchRequestDto
    runtimes: tuple[Literal["claude-code", "codex"], ...] = ()
    no_synthesis: bool = False


class CitationDto(FrozenObject):
    """The exact graph body supporting an item."""

    record_id: str
    revision: int | None


class BriefingItemDto(FrozenObject):
    """A claim and its purported citations; grounding validates these separately."""

    text: str
    citations: tuple[CitationDto, ...] = ()


class BriefingDraftDto(FrozenObject):
    """The only model-controlled fields; other model output is ignored."""

    constraints: tuple[BriefingItemDto, ...] = ()
    decisions: tuple[BriefingItemDto, ...] = ()
    context: tuple[BriefingItemDto, ...] = ()
    unconfirmed: tuple[BriefingItemDto, ...] = ()


class EvidenceDto(FrozenObject):
    """A considered record; body is present only after a successful bounded read."""

    id: str
    type: str
    title: str | None
    revision: int | None
    authority: str
    status: str | None
    superseded_by: tuple[str, ...] = ()
    migrated: bool = False
    read: bool = False
    omitted_reason: str | None = None
    body: str | None = None
    discovery: tuple[GraphNeighbourContract, ...] = ()
    warnings: tuple[str, ...] = ()


class RecommendedToolDto(FrozenObject):
    """Recommendation provenance and observed availability, never model generated."""

    catalog_id: str
    assertion_ids: tuple[str, ...]
    endorsements: tuple[AssertionSummaryContract, ...]
    endorsement: str
    runtimes: tuple[CatalogAvailabilityRuntimeContract, ...]
    usable: bool


class RecallResultDto(FrozenObject):
    """The complete deterministic envelope around the optional synthesis."""

    synthesis: Literal["briefing", "digest", "no_evidence"]
    search: RecordSearchResultDto
    records: tuple[EvidenceDto, ...]
    constraints: tuple[BriefingItemDto, ...] = ()
    decisions: tuple[BriefingItemDto, ...] = ()
    context: tuple[BriefingItemDto, ...] = ()
    unconfirmed: tuple[BriefingItemDto, ...] = ()
    unsupported: tuple[BriefingItemDto, ...] = ()
    tools: tuple[RecommendedToolDto, ...] = ()
    tools_state: str
    capabilities: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
