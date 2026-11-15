"""`IVaultReader` over a folder: regular `.md` files, no links, no hidden segments."""

import os
from pathlib import Path

from noesis.bounded_context.interop.application.ports import IVaultReader
from noesis.exceptions import VaultReadFailedError

MARKDOWN_SUFFIX: str = ".md"


def _failed(path: Path | str, error: OSError | None = None) -> VaultReadFailedError:
    reason: str = f": {error.strerror or error}" if error is not None else ""
    return VaultReadFailedError(
        f"Cannot read the vault at {path}{reason}.",
        {"path": str(path)},
        next_steps=["Check that NOESIS_VAULT_DIR is a readable folder."],
    )


class FilesystemVaultReaderAdapter(IVaultReader):
    """Read-only: it opens files for reading and never creates, renames or deletes anything."""

    def __init__(self, root: Path) -> None:
        self._root: Path = root

    def list_notes(self) -> list[str]:
        """Relative POSIX paths of every note under the root, sorted by code point."""
        if not self._root.is_dir():
            raise _failed(self._root)
        found: list[str] = []
        try:
            self._walk(self._root, "", found)
        except OSError as error:
            raise _failed(self._root, error) from error
        return sorted(found)

    def read(self, relative_path: str) -> bytes:
        """The raw bytes of one note."""
        target: Path = self._root / relative_path
        try:
            return target.read_bytes()
        except OSError as error:
            raise _failed(target, error) from error

    def _walk(self, folder: Path, prefix: str, found: list[str]) -> None:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                relative: str = f"{prefix}{entry.name}"
                if entry.is_dir(follow_symlinks=False):
                    self._walk(folder / entry.name, f"{relative}/", found)
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(MARKDOWN_SUFFIX):
                    found.append(relative)
