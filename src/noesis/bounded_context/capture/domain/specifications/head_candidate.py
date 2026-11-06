"""What the new-commit rule looks at."""

from dataclasses import dataclass
from datetime import datetime

from noesis.bounded_context.capture.domain.value_objects import WorktreeHead


@dataclass(frozen=True, slots=True, kw_only=True)
class HeadCandidate:
    """One worktree HEAD at one moment of a commit hook.

    Attributes:
        head: The worktree's HEAD.
        baseline_sha: HEAD the session last saw there, if it ever looked.
        now: Current time.
    """

    head: WorktreeHead
    baseline_sha: str | None
    now: datetime
