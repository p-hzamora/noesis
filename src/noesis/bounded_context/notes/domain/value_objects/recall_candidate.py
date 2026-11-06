"""One note the search engine returned, reduced to what ranking needs."""

from datetime import date

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_kind_enum import NoteKindEnum
from .note_origin_enum import NoteOriginEnum


class RecallCandidate(ValueObject):
    """A search hit as the recall ranking sees it.

    Relevance is only the engine's rank position; no score crosses the port.

    Attributes:
        path: Vault-relative path; identifies the note.
        kind: Note kind; None for a note outside the noesis layout.
        origin: Who wrote the note.
        updated: Last update date; None when unknown.
        rank: Position in the engine's answer, 0 is the best match.
    """

    path: str
    kind: NoteKindEnum | None
    origin: NoteOriginEnum
    updated: date | None
    rank: int = Field(ge=0)
