"""Remembers which folder a repository id stands for."""

import abc
from pathlib import Path

from noesis.bounded_context.capture.domain.value_objects import RepoId


class IRepoRegistry(abc.ABC):
    """Write-only: ids are derived from the repository, never looked up."""

    @abc.abstractmethod
    async def register(self, repo_id: RepoId, path: Path) -> None:
        """Record that `repo_id` is the repository at `path` (a no-op when already recorded)."""
        ...
