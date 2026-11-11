"""A note as listed or found by a search."""

from noesis.shared_kernel.application.dtos import BaseDto


class NoteSummaryDto(BaseDto):
    """Enough to show a note in a list and to give the curator context.

    Attributes:
        id: Stable note id (ULID).
        scope: `repo:<name>` or `topic:<name>`.
        path: Source-relative path.
        title: Note title.
        kind: Note kind name.
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        snippet: Start of the first section, for context.
    """

    id: str
    scope: str
    path: str
    title: str
    kind: str
    origin: str
    updated: str | None
    snippet: str
