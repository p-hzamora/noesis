"""There is pending work at all."""

from noesis.shared_kernel.domain.specifications import Specification

from .flush_candidate import FlushCandidate


class PendingWorkSpecification(Specification[FlushCandidate]):
    """At least one commit is pending."""

    def is_satisfied_by(self, candidate: FlushCandidate) -> bool:
        """Whether something waits to be handed over."""
        return bool(candidate.session.pending)
