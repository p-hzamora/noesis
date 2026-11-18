"""A typed relation from a source record to another Knowledge record."""

from noesis.bounded_context.knowledge.domain.value_objects.enums import RecordRelationEnum
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.shared_kernel.domain.value_objects import ValueObject


class RecordRelation(ValueObject):
    """A target record and the relation the source declares towards it."""

    target_record_id: RecordId
    relation: RecordRelationEnum
