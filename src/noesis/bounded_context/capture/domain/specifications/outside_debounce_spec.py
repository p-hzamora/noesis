"""Enough time passed since the last hand-over."""

from datetime import datetime

from noesis.bounded_context.capture.domain.specifications.flush_candidate import FlushCandidate
from noesis.shared_kernel.domain.specifications import Specification


class OutsideDebounceSpecification(Specification[FlushCandidate]):
    """Hand-overs are at least `debounce_seconds` apart; the final flush ignores the window."""

    def __init__(self, debounce_seconds: float) -> None:
        self._debounce_seconds: float = debounce_seconds

    def is_satisfied_by(self, candidate: FlushCandidate) -> bool:
        """Whether a hand-over may happen now."""
        last: datetime | None = candidate.session.cursor.handed_over_at
        if candidate.final or last is None:
            return True
        return (candidate.now - last).total_seconds() >= self._debounce_seconds
