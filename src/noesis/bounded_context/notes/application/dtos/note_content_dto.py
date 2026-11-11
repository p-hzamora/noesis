"""A note read in full."""

from noesis.shared_kernel.application.dtos import BaseDto


class NoteContentDto(BaseDto):
    """One note with its whole text.

    Attributes:
        id: Stable note id (ULID).
        scope: `repo:<name>` or `topic:<name>`.
        path: Source-relative path.
        title: Note title.
        kind: Note kind name.
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        content: The file's text, frontmatter included.
    """

    id: str
    scope: str
    path: str
    title: str
    kind: str
    origin: str
    updated: str | None
    content: str
