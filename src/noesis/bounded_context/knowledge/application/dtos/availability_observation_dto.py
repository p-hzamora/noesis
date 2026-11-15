"""One cataloged entry assessed against one runtime inventory."""

from noesis.bounded_context.knowledge.application.dtos.availability_reason_enum import (
    AvailabilityReasonEnum,
)
from noesis.bounded_context.knowledge.application.dtos.availability_status_enum import (
    AvailabilityStatusEnum,
)
from noesis.bounded_context.knowledge.application.dtos.runtime_enum import RuntimeEnum
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class AvailabilityObservationDto(BaseDto):
    """One cataloged entry assessed against one runtime inventory.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        runtime: Runtime observed.
        host: Machine observed.
        observed_at: ISO-8601 UTC time of the observation.
        status: `available`, `unavailable` or `unknown`.
        reason: Why.
        observed_version: Version of the matching installed artifact, when there is one.
        version_drift: On `available` only: whether declared and observed versions differ.
        missing_prerequisites: Prerequisites (`kind:name`) with no installed match.
    """

    entry_id: str
    kind: CatalogEntryKindEnum
    name: str
    runtime: RuntimeEnum
    host: str
    observed_at: str
    status: AvailabilityStatusEnum
    reason: AvailabilityReasonEnum
    observed_version: str | None = None
    version_drift: bool | None = None
    missing_prerequisites: tuple[str, ...] = ()
