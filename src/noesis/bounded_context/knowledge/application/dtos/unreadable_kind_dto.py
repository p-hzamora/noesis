"""A kind a probe could not enumerate."""

from noesis.bounded_context.knowledge.application.dtos.availability_reason_enum import (
    AvailabilityReasonEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class UnreadableKindDto(BaseDto):
    """A kind a probe could not enumerate.

    Attributes:
        kind: The kind.
        reason: `probe_failed` (it tried and could not) or `kind_not_probed` (no probe exists).
    """

    kind: CatalogEntryKindEnum
    reason: AvailabilityReasonEnum
