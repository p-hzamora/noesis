"""Questions about the machine that diagnostics asks."""

import abc
from pathlib import Path


class IEnvironmentProbe(abc.ABC):
    """Read-only view of the file system and the executable search path."""

    @abc.abstractmethod
    def exists(self, path: Path) -> bool:
        """Whether `path` exists."""
        ...

    @abc.abstractmethod
    def is_file(self, path: Path) -> bool:
        """Whether `path` is an existing regular file."""
        ...

    @abc.abstractmethod
    def is_writable_folder(self, folder: Path) -> bool:
        """Whether `folder` exists and a file can be created in it."""
        ...

    @abc.abstractmethod
    def find_executable(self, command: str) -> str | None:
        """Full path of `command` on the executable search path, or None."""
        ...

    @abc.abstractmethod
    def list_entries(self, folder: Path) -> tuple[str, ...]:
        """Names of the files and non-empty folders directly inside `folder` (empty when it is missing)."""
        ...
