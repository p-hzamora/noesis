"""`IEnvironmentProbe` over the real file system and `PATH`."""

import shutil
import tempfile
from pathlib import Path

from noesis.diagnostics.application.ports.probes import IEnvironmentProbe


class SystemEnvironmentProbeAdapter(IEnvironmentProbe):
    """Asks the operating system; never modifies anything that remains afterwards."""

    def exists(self, path: Path) -> bool:
        """Whether `path` exists."""
        return path.exists()

    def is_file(self, path: Path) -> bool:
        """Whether `path` is a regular file."""
        return path.is_file()

    def is_writable_folder(self, folder: Path) -> bool:
        """Whether a temporary file can be created (and is removed again) in `folder`."""
        if not folder.is_dir():
            return False
        try:
            with tempfile.NamedTemporaryFile(dir=folder):
                return True
        except OSError:
            return False

    def find_executable(self, command: str) -> str | None:
        """`shutil.which` of `command`."""
        return shutil.which(command)

    def list_entries(self, folder: Path) -> tuple[str, ...]:
        """Sorted names directly inside `folder`, skipping folders with no file in them.

        Obsidian's MCP does not list empty folders, so they would not match its listing.
        Empty when `folder` cannot be listed.
        """
        try:
            return tuple(
                sorted(
                    entry.name
                    for entry in folder.iterdir()
                    if not entry.is_dir() or any(path.is_file() for path in entry.rglob("*"))
                )
            )
        except OSError:
            return ()
