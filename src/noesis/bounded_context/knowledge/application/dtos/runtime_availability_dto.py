"""The observations of one runtime."""

from noesis.bounded_context.knowledge.application.dtos.availability_observation_dto import (
    AvailabilityObservationDto,
)
from noesis.bounded_context.knowledge.application.dtos.availability_summary_dto import (
    AvailabilitySummaryDto,
)
from noesis.bounded_context.knowledge.application.dtos.runtime_enum import RuntimeEnum
from noesis.bounded_context.knowledge.application.dtos.unreadable_kind_dto import UnreadableKindDto
from noesis.shared_kernel.application.dtos import BaseDto


class RuntimeAvailabilityDto(BaseDto):
    """The observations of one runtime.

    Attributes:
        runtime: The runtime.
        host: Machine observed.
        observed_at: ISO-8601 UTC time of the observation.
        observations: One per selected entry.
        summary: Counts per status.
        unreadable_kinds: Kinds that could not be read.
    """

    runtime: RuntimeEnum
    host: str
    observed_at: str
    observations: tuple[AvailabilityObservationDto, ...] = ()
    summary: AvailabilitySummaryDto
    unreadable_kinds: tuple[UnreadableKindDto, ...] = ()
