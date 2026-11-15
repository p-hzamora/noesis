"""A note's bytes decoded and split into header text and body (step 0)."""

from noesis.bounded_context.interop.domain.value_objects.note_enums import NoteBlockReasonEnum
from noesis.shared_kernel.domain.value_objects import ValueObject


class SplitNote(ValueObject):
    """Result of step 0.

    Attributes:
        failure: `not_text` or `invalid_header`, when the note cannot be read; else None.
        header_text: The text between the `---` lines, or None when there is no header.
        body: Everything after the header (the whole text without one); empty on a failure.
    """

    failure: NoteBlockReasonEnum | None = None
    header_text: str | None = None
    body: str = ""
