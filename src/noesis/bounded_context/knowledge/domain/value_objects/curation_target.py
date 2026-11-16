"""An existing record a candidate names as its target, as the store holds it."""

from noesis.shared_kernel.domain.value_objects import ValueObject

MIGRATED_TAG: str = "origin:migrated"
"""Tag C3 puts on migrated records; only the Q-018 exception of policy row 10 reads it."""


class CurationTarget(ValueObject):
    """The target of a candidate, read in the active space.

    Every record is graph-owned (D23), so it carries no ownership.

    Attributes:
        record_id: The record's id.
        record_type: `knowledge`, `experience`, ...
        status: Its status, the derived one when the store derives it; None for types without.
        project_key: Key of its project; None when space-wide.
        head_revision: Head revision number; None for types without revisions.
        tags: Its applicability tags.
    """

    record_id: str
    record_type: str
    status: str | None = None
    project_key: str | None = None
    head_revision: int | None = None
    tags: tuple[str, ...] = ()
