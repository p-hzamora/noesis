"""Read-only questions about a repository."""

import abc
from collections.abc import Sequence
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import RepositoryLocationDto
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, WorktreeHead


class IVcsReader(abc.ABC):
    """What Capture asks version control."""

    @abc.abstractmethod
    async def common_dir(self, cwd: Path) -> RepositoryLocationDto | None:
        """The repository containing `cwd` (the same for every linked worktree), or None."""
        ...

    @abc.abstractmethod
    async def worktrees(self, common_dir: Path) -> list[WorktreeHead]:
        """HEAD of every worktree of the repository (the bare folder itself excluded)."""
        ...

    @abc.abstractmethod
    async def head_commit(self, root: Path) -> CommitRecord | None:
        """HEAD with its subject and size, or None in an empty repository."""
        ...

    @abc.abstractmethod
    async def branch(self, root: Path) -> str:
        """Current branch name."""
        ...

    @abc.abstractmethod
    async def stat_lines(self, root: Path, shas: Sequence[str], *, limit: int) -> list[str]:
        """`--stat` lines (names and counts, never the diff) of the commits, at most `limit`."""
        ...
