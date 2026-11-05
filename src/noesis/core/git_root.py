"""Locating the git repository a command runs in."""

from pathlib import Path


def find_git_root(start: Path) -> Path | None:
    """The nearest directory from `start` upwards that holds `.git`.

    `.git` may be a folder or a file (a linked worktree), so both count.

    Args:
        start: Directory to begin the search in.

    Returns:
        The repository root, or None outside a repository.
    """
    current: Path = start.expanduser().resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None
