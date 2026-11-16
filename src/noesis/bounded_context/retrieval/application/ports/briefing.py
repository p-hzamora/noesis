"""Retrieval-owned doors for review, endorsements, availability and synthesis."""

from collections.abc import Sequence
from typing import Protocol

from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    CatalogAvailabilityRequestContract,
    CatalogAvailabilityResultContract,
    RecordReviewStateContract,
)

from ..dtos.briefing_dtos import BriefingDraftDto, EvidenceDto


class IReviewReader(Protocol):
    """Read current effective review states in one space."""

    async def get_states(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[RecordReviewStateContract]: ...


class IRecommendationReader(Protocol):
    """Read live recommendation assertions by evidence subjects."""

    async def by_subjects(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[AssertionSummaryContract]: ...


class ICatalogAvailability(Protocol):
    """Observe catalog entries in the requested runtimes."""

    async def check(
        self, request: CatalogAvailabilityRequestContract
    ) -> CatalogAvailabilityResultContract: ...


class IBriefingModel(Protocol):
    """Synthesize from redacted evidence; no authority or tool decisions."""

    async def synthesize(self, task: str, evidence: Sequence[EvidenceDto]) -> BriefingDraftDto: ...


class IBriefingRedactor(Protocol):
    """Mask secrets before evidence leaves the application."""

    def redact(self, text: str) -> tuple[str, int]: ...
