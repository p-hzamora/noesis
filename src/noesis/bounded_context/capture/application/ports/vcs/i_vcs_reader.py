"""Read-only questions about a repository."""

import abc
from collections.abc import Sequence
from pathlib import Path

from noesis.bounded_context.capture.domain.value_objects import CommitRecord


class IVcsReader(abc.ABC):
    """What Capture asks version control."""

    @abc.abstractmethod
    async def repository_root(self, cwd: Path) -> Path | None:
        """Root of the repository containing `cwd`, or None outside one."""
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
