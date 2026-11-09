"""Result of recalling notes for a task."""

from typing import Literal

from noesis.shared_kernel.application.dtos import BaseDto
from noesis.shared_kernel.enums import SearchEngineEnum

from .recall_briefing_dto import RecallBriefingDto
from .recall_entry_dto import RecallEntryDto


class RecallDigestDto(BaseDto):
    """The notes worth reading for a task, best first, and the briefing written from them.

    Attributes:
        entries: With a briefing, the notes that were read for it; in a digest, the notes
            worth reading and within the budget. Most relevant first.
        considered: How many notes the search returned and the ranking looked at.
        omitted: How many of those are not in `entries` (past the limit or over the budget).
        backend: Repository that actually answered.
        synthesis: `briefing` (an agent wrote `briefing`), `no_evidence` (the search found no
            note, so no agent ran) or `digest` (synthesis was switched off).
        briefing: The agent's briefing; None unless `synthesis` is `briefing`.
        warnings: What limited the briefing: notes that could not be read, text that was cut,
            secrets that were masked.
    """

    entries: tuple[RecallEntryDto, ...]
    considered: int
    omitted: int
    backend: SearchEngineEnum
    synthesis: Literal["briefing", "no_evidence", "digest"] = "digest"
    briefing: RecallBriefingDto | None = None
    warnings: tuple[str, ...] = ()
