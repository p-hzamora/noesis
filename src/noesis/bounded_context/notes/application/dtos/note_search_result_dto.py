"""Result of searching notes."""

from noesis.shared_kernel.application.dtos import BaseDto
from noesis.shared_kernel.enums import SearchEngineEnum

from .note_summary_dto import NoteSummaryDto


class NoteSearchResultDto(BaseDto):
    """Notes best match first, and which backend produced them.

    `backend` is whoever actually answered, so it differs from the configured one when the
    search degraded to the files.

    Attributes:
        notes: The notes.
        backend: Repository that answered; only a backend noesis implements.
    """

    notes: tuple[NoteSummaryDto, ...]
    backend: SearchEngineEnum
