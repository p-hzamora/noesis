"""`IFileReader` over the local filesystem."""

import os
from pathlib import Path

from noesis.bounded_context.interop.application.ports import IFileReader
from noesis.exceptions import FileReadFailedError


def _failed(path: str, reason: str) -> FileReadFailedError:
    return FileReadFailedError(
        f"Cannot read {path}: {reason}.",
        {"path": path},
        next_steps=["Give the path of a readable regular file."],
    )


class FilesystemFileReaderAdapter(IFileReader):
    """Read-only: resolves links and reads bytes."""

    def resolve(self, path: str) -> str:
        """The absolute path with links resolved; the target must be a readable regular file."""
        try:
            resolved: Path = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise _failed(path, "no such file") from error
        if not resolved.is_file():
            raise _failed(path, "not a regular file")
        if not os.access(resolved, os.R_OK):
            raise _failed(str(resolved), "permission denied")
        return str(resolved)

    def read(self, absolute_path: str) -> bytes:
        """The raw bytes of the file."""
        try:
            return Path(absolute_path).read_bytes()
        except OSError as error:
            raise _failed(absolute_path, error.strerror or "read failed") from error
