"""Result of listing or searching notes."""

from noesis.shared_kernel.application.dtos import BaseDto

from .note_summary_dto import NoteSummaryDto


class NoteListDto(BaseDto):
    """Notes, best match first for searches.

    Attributes:
        notes: The notes.
    """

    notes: tuple[NoteSummaryDto, ...]
