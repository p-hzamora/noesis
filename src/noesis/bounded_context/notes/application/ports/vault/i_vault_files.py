"""Raw access to the files of the vault, for the work that moves files rather than notes."""

import abc
from collections.abc import Sequence


class IVaultFiles(abc.ABC):
    """Every path is `/`-separated and relative to the vault root; none may escape it."""

    @abc.abstractmethod
    async def list_files(self) -> list[str]:
        """Every file of the vault, hidden folders included, sorted."""
        ...

    @abc.abstractmethod
    async def list_dirs(self) -> list[str]:
        """Every folder of the vault below the root, hidden folders included, sorted."""
        ...

    @abc.abstractmethod
    async def read(self, path: str) -> bytes:
        """The file's bytes."""
        ...

    @abc.abstractmethod
    async def write(self, path: str, data: bytes) -> None:
        """Atomically store `data` at `path`, creating folders; an existing file is replaced."""
        ...

    @abc.abstractmethod
    async def delete(self, path: str) -> None:
        """Remove one file (never a folder)."""
        ...

    @abc.abstractmethod
    async def remove_empty_dirs(self, paths: Sequence[str]) -> list[str]:
        """Remove each of the folders that is empty, deepest first; return those removed.

        A folder that holds anything, or is not a folder, is left as it is: nothing is deleted
        recursively.
        """
        ...
