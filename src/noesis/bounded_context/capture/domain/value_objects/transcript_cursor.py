"""How far the transcript was read at the last hand-over, and when."""

from datetime import datetime

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject


class TranscriptCursor(ValueObject):
    """Position in the transcript up to which work has been handed over.

    Attributes:
        offset: Byte offset into the transcript file.
        handed_over_at: Time of the last hand-over, or None before the first.
    """

    offset: int = Field(default=0, ge=0)
    handed_over_at: datetime | None = None
