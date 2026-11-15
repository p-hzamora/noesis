"""What makes two assertions the same statement."""

from noesis.bounded_context.knowledge.domain.value_objects.enums import AssertionPredicateEnum
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.space_id import SpaceId
from noesis.shared_kernel.domain.value_objects import ValueObject


class StatementKey(ValueObject):
    """Space, predicate, subject, object and project: one live assertion per key.

    Attributes:
        space_id: Space of the assertion.
        predicate: How subject relates to object.
        subject_id: Subject record.
        object_id: Object record.
        project_id: The assertion's project; None when space-wide.
    """

    space_id: SpaceId
    predicate: AssertionPredicateEnum
    subject_id: RecordId
    object_id: RecordId
    project_id: RecordId | None = None
