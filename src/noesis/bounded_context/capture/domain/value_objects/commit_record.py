"""One finished commit waiting to be handed over."""

from typing import Self

from noesis.shared_kernel.domain.value_objects import ValueObject

from .diff_size import DiffSize


class CommitRecord(ValueObject):
    """A commit as Capture needs it.

    Attributes:
        sha: Full hash.
        subject: First line of the message.
        size: How big it is.
        branch: Branch it was committed on (empty on records made before branches were kept).
        worktree: Worktree folder it was committed in (empty on older records).
    """

    sha: str
    subject: str
    size: DiffSize
    branch: str = ""
    worktree: str = ""

    def committed_in(self, *, worktree: str, branch: str) -> Self:
        """The same commit, labelled with where it was made."""
        return self.model_copy(update={"worktree": worktree, "branch": branch})
