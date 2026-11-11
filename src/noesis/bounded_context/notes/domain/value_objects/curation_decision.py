"""What the curator decided about one candidate piece of knowledge."""

from enum import StrEnum

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_kind import NoteKind
from .note_section import NoteSection
from .note_slug import NoteSlug


class CurationActionEnum(StrEnum):
    """Create a note, update an existing auto note, or skip the candidate."""

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"


class NoteDraft(ValueObject):
    """The curator's proposed content for a note.

    Attributes:
        kind: What the note records.
        slug: File name; reuse an existing auto note's slug to update it.
        title: Note title.
        sections: Proposed sections (missing required ones are filled by the domain).
    """

    kind: NoteKind
    slug: NoteSlug
    title: str
    sections: tuple[NoteSection, ...]


class CurationDecision(ValueObject):
    """One verdict of the curator.

    Attributes:
        action: What to do.
        candidate: Short name of the candidate knowledge, for reports.
        reason: Why, in one sentence (used verbatim in skip reports).
        draft: The note content for CREATE and UPDATE; None for SKIP.
    """

    action: CurationActionEnum
    candidate: str
    reason: str
    draft: NoteDraft | None = None
