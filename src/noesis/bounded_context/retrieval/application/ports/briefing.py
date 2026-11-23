"""Retrieval-owned doors for synthesis and redaction."""

import abc
from collections.abc import Sequence

from ..dtos.briefing_dtos import BriefingDraftDto, EvidenceDto


class IBriefingModel(abc.ABC):
    """Synthesize from redacted evidence; no authority or tool decisions."""

    @abc.abstractmethod
    async def synthesize(self, task: str, evidence: Sequence[EvidenceDto]) -> BriefingDraftDto:
        """Draft a briefing for `task` from the redacted `evidence`."""
        ...


class IBriefingRedactor(abc.ABC):
    """Mask secrets before evidence leaves the application."""

    @abc.abstractmethod
    def redact(self, text: str) -> tuple[str, int]:
        """The masked text and how many secrets were masked."""
        ...
