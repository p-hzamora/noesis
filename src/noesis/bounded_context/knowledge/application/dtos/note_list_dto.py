"""Result of listing or searching notes."""

from noesis.bounded_context.knowledge.application.dtos.note_summary_dto import NoteSummaryDto
from noesis.shared_kernel.application.dtos import BaseDto


class NoteListDto(BaseDto):
    """Notes, best match first for searches.

    Attributes:
        notes: The notes.
    """

    notes: tuple[NoteSummaryDto, ...]
