"""A grouped link to another Knowledge record."""

from typing import Literal

from pydantic import Field, field_validator

from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.shared_kernel.domain.value_objects import ValueObject


class RecordLink(ValueObject):
    """A target, kind, occurrence count and canonical anchor set."""

    target_record_id: RecordId
    link_type: Literal["links_to", "embeds"]
    count: int = Field(ge=1)
    anchors: tuple[str, ...] = ()

    @field_validator("anchors")
    @classmethod
    def canonical_anchors(cls, anchors: tuple[str, ...]) -> tuple[str, ...]:
        """Keep non-empty distinct anchors in lexical order."""
        return tuple(sorted(set(filter(None, anchors))))
