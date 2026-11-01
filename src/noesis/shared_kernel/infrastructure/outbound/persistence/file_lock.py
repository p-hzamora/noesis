"""Exclusive advisory file lock (POSIX `flock`), usable from async code."""

import asyncio
import fcntl
import os
import time
from pathlib import Path
from types import TracebackType
from typing import Self

POLL_SECONDS: float = 0.02


class FileLock:
    """Holds `flock(LOCK_EX)` on a lock file while the `async with` block runs.

    Two hooks of the same session (e.g. Stop and SessionEnd) take turns instead of
    interleaving their read-modify-write of the session state.
    """

    def __init__(self, path: Path, *, timeout_seconds: float) -> None:
        self._path: Path = path
        self._timeout_seconds: float = timeout_seconds
        self._descriptor: int | None = None

    async def __aenter__(self) -> Self:
        """Wait for the lock, up to the timeout.

        Raises:
            TimeoutError: Another holder kept the lock for longer than the timeout.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline: float = time.monotonic() + self._timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise TimeoutError(
                        f"lock {self._path} held for more than {self._timeout_seconds}s"
                    ) from None
                await asyncio.sleep(POLL_SECONDS)
        self._descriptor = descriptor
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._descriptor is not None:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._descriptor = None
