"""The commit a worktree stands on."""

from datetime import datetime

from noesis.shared_kernel.domain.value_objects import ValueObject


class WorktreeHead(ValueObject):
    """HEAD of one worktree of a repository.

    Attributes:
        path: Absolute worktree folder.
        sha: HEAD commit.
        branch: Checked-out branch (`HEAD` when detached).
        committed_at: When HEAD was committed.
    """

    path: str
    sha: str
    branch: str
    committed_at: datetime
