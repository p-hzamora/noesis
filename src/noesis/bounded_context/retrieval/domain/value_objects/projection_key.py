"""The identity of one indexed entry: a record at a revision."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class ProjectionKey(ValueObject):
    """A record and the revision a projection holds for it.

    Attributes:
        record_id: The record.
        revision: The revision; null for types without revisions (an Experience).
    """

    record_id: str
    revision: int | None = None
