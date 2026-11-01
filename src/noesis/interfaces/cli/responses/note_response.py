"""`noesis knowledge list|search` output."""

from noesis.utils import FrozenObject


class NoteResponse(FrozenObject):
    """A note as listed by `noesis knowledge list|search`.

    Attributes:
        path: Vault-relative path.
        title: Note title.
        kind: Note kind value.
        origin: `manual` or `auto`.
        updated: Last update date (ISO), when known.
        snippet: Start of the first section, for context.
    """

    path: str
    title: str
    kind: str
    origin: str
    updated: str | None
    snippet: str


class NoteListResponse(FrozenObject):
    """`noesis knowledge list|search`: notes, best match first for searches.

    Attributes:
        notes: The notes.
    """

    notes: tuple[NoteResponse, ...]
