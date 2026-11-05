"""One `## Heading` block of a note."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class NoteSection(ValueObject):
    """A heading and its Markdown body.

    Attributes:
        heading: Text of the `##` heading.
        body: Markdown under it.
    """

    heading: str
    body: str
