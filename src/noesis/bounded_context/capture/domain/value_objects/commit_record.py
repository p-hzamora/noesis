"""One finished commit waiting to be handed over."""

from noesis.shared_kernel.domain.value_objects import ValueObject

from .diff_size import DiffSize


class CommitRecord(ValueObject):
    """A commit as Capture needs it.

    Attributes:
        sha: Full hash.
        subject: First line of the message.
        size: How big it is.
    """

    sha: str
    subject: str
    size: DiffSize
