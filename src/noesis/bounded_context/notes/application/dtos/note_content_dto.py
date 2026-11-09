"""A note read in full."""

from noesis.shared_kernel.application.dtos import BaseDto


class NoteContentDto(BaseDto):
    """One note with its whole text.

    Attributes:
        path: Vault-relative path.
        title: Note title.
        kind: Note kind value; None for a note outside the noesis layout.
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        content: The file's text, frontmatter included.
    """

    path: str
    title: str
    kind: str | None
    origin: str
    updated: str | None
    content: str
