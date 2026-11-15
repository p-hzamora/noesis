"""Why an observation has its status (`none` for `available`)."""

from enum import StrEnum


class AvailabilityReasonEnum(StrEnum):
    """Why an observation has its status (`none` for `available`)."""

    NONE = "none"
    NOT_INSTALLED = "not_installed"
    PREREQUISITE_MISSING = "prerequisite_missing"
    PROBE_FAILED = "probe_failed"
    KIND_NOT_PROBED = "kind_not_probed"
