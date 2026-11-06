"""Where a repository lives, as version control reports it."""

from pathlib import Path

from noesis.shared_kernel.application.dtos import BaseDto


class RepositoryLocationDto(BaseDto):
    """The identity of the repository a directory belongs to.

    Attributes:
        common_dir: The resolved git directory every worktree of the repository shares.
        root: The main worktree (the repository folder itself when bare): the path notes and
            briefs refer to.
        name: The folder name the repository is known by.
    """

    common_dir: Path
    root: Path
    name: str
