"""Result of `check`."""

from noesis.bounded_context.knowledge.application.dtos.catalog_entry_dto import CatalogEntryDto
from noesis.bounded_context.knowledge.application.dtos.runtime_availability_dto import (
    RuntimeAvailabilityDto,
)
from noesis.shared_kernel.application.dtos import BaseDto


class AvailabilityReportDto(BaseDto):
    """Result of `check`.

    Attributes:
        runtimes: One block per resolved runtime, in the order asked.
        entries: The entries that were assessed, with their head content.
        next_steps: The location of each unavailable entry, and `noesis catalog revise` for
            each entry whose installed version drifted.
    """

    runtimes: tuple[RuntimeAvailabilityDto, ...] = ()
    entries: tuple[CatalogEntryDto, ...] = ()
    next_steps: tuple[str, ...] = ()
