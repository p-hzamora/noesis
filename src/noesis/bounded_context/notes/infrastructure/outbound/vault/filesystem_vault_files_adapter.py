"""`IVaultFiles` over a folder on disk."""

import os
from collections.abc import Sequence
from pathlib import Path

from noesis.bounded_context.notes.application.ports.vault import IVaultFiles
from noesis.exceptions import NoteStorageError


class FilesystemVaultFilesAdapter(IVaultFiles):
    """Files under one root; every write is atomic and nothing is ever deleted recursively."""

    def __init__(self, root: Path) -> None:
        self._root: Path = root.expanduser().resolve()

    def _path(self, relative: str) -> Path:
        parts: list[str] = relative.split("/")
        if not relative or relative.startswith("/") or any(p in {"", ".", ".."} for p in parts):
            raise NoteStorageError(
                f"Refusing to touch {relative!r}: not a path inside the vault.", {"path": relative}
            )
        return self._root.joinpath(*parts)

    async def list_files(self) -> list[str]:
        """Every file below the root (symbolic links are not followed into folders)."""
        found: list[str] = []
        for folder, _dirs, names in os.walk(self._root):
            found += [(Path(folder) / name).relative_to(self._root).as_posix() for name in names]
        return sorted(found)

    async def list_dirs(self) -> list[str]:
        """Every folder below the root."""
        found: list[str] = []
        for folder, dirs, _names in os.walk(self._root):
            found += [(Path(folder) / name).relative_to(self._root).as_posix() for name in dirs]
        return sorted(found)

    async def read(self, path: str) -> bytes:
        """The file's bytes."""
        try:
            return self._path(path).read_bytes()
        except OSError as error:
            raise NoteStorageError(f"Cannot read {path}: {error}", {"path": path}) from error

    async def write(self, path: str, data: bytes) -> None:
        """Write to a temporary file beside the target, then rename it over the target."""
        target: Path = self._path(path)
        temporary: Path = target.with_name(f".{target.name}.noesis-tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(data)
            if target.exists():
                temporary.chmod(target.stat().st_mode & 0o7777)
            temporary.replace(target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise NoteStorageError(f"Cannot write {path}: {error}", {"path": path}) from error

    async def delete(self, path: str) -> None:
        """Unlink one file."""
        try:
            self._path(path).unlink()
        except OSError as error:
            raise NoteStorageError(f"Cannot delete {path}: {error}", {"path": path}) from error

    async def remove_empty_dirs(self, paths: Sequence[str]) -> list[str]:
        """`rmdir` each folder, deepest first; a folder with content raises and is skipped."""
        removed: list[str] = []
        for relative in sorted(paths, key=lambda p: (-p.count("/"), p)):
            try:
                self._path(relative).rmdir()
            except OSError:
                continue
            removed.append(relative)
        return removed
