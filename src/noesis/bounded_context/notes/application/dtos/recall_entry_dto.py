"""One note in a recall digest."""

from noesis.shared_kernel.application.dtos import BaseDto


class RecallEntryDto(BaseDto):
    """A pointer to a note, never its body.

    Attributes:
        kind: Note kind value; None for a note outside the noesis layout.
        title: Note title.
        path: Vault-relative path, to read the full note.
        date: Last update date (ISO), when known.
        snippet: Start of the first section, possibly shortened to fit the budget.
    """

    kind: str | None
    title: str
    path: str
    date: str | None
    snippet: str
