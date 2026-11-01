"""What the hand-over rules look at."""

from dataclasses import dataclass
from datetime import datetime

from noesis.bounded_context.capture.domain.entities import CaptureSession


@dataclass(frozen=True, slots=True, kw_only=True)
class FlushCandidate:
    """A session at one moment of a flush.

    Attributes:
        session: The capture session.
        now: Current time.
        final: Whether this is the session's last chance (session end).
    """

    session: CaptureSession
    now: datetime
    final: bool
