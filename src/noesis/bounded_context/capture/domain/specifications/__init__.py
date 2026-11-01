"""Rules deciding whether pending work is ready to hand over."""

from noesis.bounded_context.capture.domain.specifications.flush_candidate import FlushCandidate
from noesis.bounded_context.capture.domain.specifications.outside_debounce_spec import (
    OutsideDebounceSpecification,
)
from noesis.bounded_context.capture.domain.specifications.pending_work_spec import (
    PendingWorkSpecification,
)
from noesis.bounded_context.capture.domain.specifications.significant_change_spec import (
    SignificantChangeSpecification,
)

__all__ = [
    "FlushCandidate",
    "OutsideDebounceSpecification",
    "PendingWorkSpecification",
    "SignificantChangeSpecification",
]
