"""A worktree HEAD that looks like the commit that just ran."""

from noesis.shared_kernel.domain.specifications import Specification

from .head_candidate import HeadCandidate

DEFAULT_WINDOW_SECONDS: float = 120.0


class NewCommitCandidateSpecification(Specification[HeadCandidate]):
    """HEAD moved since the session last looked, and was committed within the window.

    The window keeps an old commit (a worktree the session never looked at before) from being
    mistaken for the commit that just ran. `now` comes from the caller, so the rule stays pure.
    """

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        self._window_seconds: float = window_seconds

    def is_satisfied_by(self, candidate: HeadCandidate) -> bool:
        """Whether this HEAD is a new commit of the session."""
        if candidate.head.sha == candidate.baseline_sha:
            return False
        age: float = (candidate.now - candidate.head.committed_at).total_seconds()
        return age <= self._window_seconds
