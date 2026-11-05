"""How the installed checkout compares with its origin."""

from enum import StrEnum


class UpdateVerdictEnum(StrEnum):
    """UP_TO_DATE: same commit. BEHIND: origin has commits the checkout lacks. AHEAD: the
    checkout has commits origin lacks. DIVERGED: both have commits the other lacks.
    UNKNOWN: it could not be told (not a checkout, no origin, origin unreachable)."""

    UP_TO_DATE = "up_to_date"
    BEHIND = "behind"
    AHEAD = "ahead"
    DIVERGED = "diverged"
    UNKNOWN = "unknown"
