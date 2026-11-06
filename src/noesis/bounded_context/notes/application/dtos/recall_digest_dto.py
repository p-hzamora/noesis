"""Result of recalling notes for a task."""

from noesis.shared_kernel.application.dtos import BaseDto
from noesis.shared_kernel.enums import SearchEngineEnum

from .recall_entry_dto import RecallEntryDto


class RecallDigestDto(BaseDto):
    """The notes worth reading for a task, best first, within the limit and the budget.

    Attributes:
        entries: The digest, most relevant first.
        considered: How many notes the search returned and the ranking looked at.
        omitted: How many of those are not in `entries` (past the limit or over the budget).
        backend: Repository that actually answered.
    """

    entries: tuple[RecallEntryDto, ...]
    considered: int
    omitted: int
    backend: SearchEngineEnum
