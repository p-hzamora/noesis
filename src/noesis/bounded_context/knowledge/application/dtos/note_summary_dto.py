"""A note as listed or found by a search."""

from noesis.shared_kernel.application.dtos import BaseDto


class NoteSummaryDto(BaseDto):
    """Enough to show a note in a list and to give the curator context.

    Attributes:
        path: Vault-relative path.
        title: Note title.
        kind: Note kind value; None for a note outside the noesis layout (found by Obsidian search).
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        snippet: Start of the first section, for context.
    """

    path: str
    title: str
    kind: str | None
    origin: str
    updated: str | None
    snippet: str
