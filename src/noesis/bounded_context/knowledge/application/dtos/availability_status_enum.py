"""Whether a cataloged capability can be used right now, as observed."""

from enum import StrEnum


class AvailabilityStatusEnum(StrEnum):
    """Whether a cataloged capability can be used right now, as observed."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
