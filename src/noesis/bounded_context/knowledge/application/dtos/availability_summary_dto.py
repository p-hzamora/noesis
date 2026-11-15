"""Observation counts of one runtime block."""

from noesis.shared_kernel.application.dtos import BaseDto


class AvailabilitySummaryDto(BaseDto):
    """Observation counts of one runtime block.

    Attributes:
        available: Entries `available`.
        unavailable: Entries `unavailable`.
        unknown: Entries `unknown`.
    """

    available: int = 0
    unavailable: int = 0
    unknown: int = 0
