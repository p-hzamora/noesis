"""What happens to a work brief when it is ready."""

from enum import StrEnum


class CaptureModeEnum(StrEnum):
    """LIVE hands briefs to the curator; DRY_RUN only records what would be handed over."""

    LIVE = "live"
    DRY_RUN = "dry-run"
