"""The pending work is big enough to be worth a curator run."""

from noesis.bounded_context.capture.domain.value_objects import DiffSize
from noesis.shared_kernel.domain.specifications import Specification

from .flush_candidate import FlushCandidate


class SignificantChangeSpecification(Specification[FlushCandidate]):
    """Pending commits together touch `min_files` files or change `min_lines` lines; their type is irrelevant."""

    def __init__(self, *, min_files: int, min_lines: int) -> None:
        self._min_files: int = min_files
        self._min_lines: int = min_lines

    def is_satisfied_by(self, candidate: FlushCandidate) -> bool:
        """Whether the summed size reaches either threshold."""
        size: DiffSize = candidate.session.pending_size
        return size.files >= self._min_files or size.lines >= self._min_lines
