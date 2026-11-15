"""What the statement and authority policies need to know about a referenced record."""

from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    RecordStatusEnum,
    RecordTypeEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.space_id import SpaceId
from noesis.shared_kernel.domain.value_objects import ValueObject


class RecordReference(ValueObject):
    """A record seen from outside its aggregate.

    Attributes:
        record_id: The record's id.
        record_type: Its type.
        space_id: Its space.
        project_id: Its applicability project; None when space-wide or not applicable.
        effective_status: Derived status; None for types without status.
        head_revision: Head revision; None for types without revisions.
    """

    record_id: RecordId
    record_type: RecordTypeEnum
    space_id: SpaceId
    project_id: RecordId | None = None
    effective_status: RecordStatusEnum | None = None
    head_revision: int | None = None
