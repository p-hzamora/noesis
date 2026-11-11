"""What a new or revised note needs from outside the domain: identity, path and sections."""

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_id import NoteId
from .note_path import NotePath


class NotePlacement(ValueObject):
    """The manifest-derived facts the application hands the policy for one decision.

    Attributes:
        id: Id for a note this decision creates.
        path: Free path for a note this decision creates.
        required_sections: Headings every note of the draft's kind has, in order.
    """

    id: NoteId
    path: NotePath
    required_sections: tuple[str, ...]
