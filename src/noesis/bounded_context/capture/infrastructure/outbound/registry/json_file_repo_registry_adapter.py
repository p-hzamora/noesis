"""`IRepoRegistry` keeping `repos.json`: repository id to folder, in the state folder."""

from pathlib import Path

from noesis.bounded_context.capture.application.ports.registry import IRepoRegistry
from noesis.bounded_context.capture.domain.value_objects import RepoId
from noesis.exceptions import CaptureStateError
from noesis.shared_kernel.domain import JsonObject
from noesis.shared_kernel.infrastructure.outbound.persistence import (
    FileLock,
    read_json_object,
    write_json_atomic,
)

REPOS_KEY: str = "repos"


class JsonFileRepoRegistryAdapter(IRepoRegistry):
    """Writes only when the mapping changes, under a file lock, atomically."""

    def __init__(self, file: Path, *, lock_timeout_seconds: float) -> None:
        self._file: Path = file
        self._lock_timeout_seconds: float = lock_timeout_seconds

    async def register(self, repo_id: RepoId, path: Path) -> None:
        """Record `repo_id` -> `path`.

        Raises:
            CaptureStateError: The registry stayed locked longer than the timeout.
        """
        if self._read().get(repo_id.value) == str(path):
            return  # the common case: nothing to lock or write
        lock = FileLock(self._file.with_suffix(".lock"), timeout_seconds=self._lock_timeout_seconds)
        try:
            async with lock:
                repos: dict[str, str] = self._read()
                if repos.get(repo_id.value) == str(path):
                    return
                repos[repo_id.value] = str(path)
                document: JsonObject = {REPOS_KEY: dict(repos)}
                write_json_atomic(self._file, document)
        except TimeoutError as error:
            raise CaptureStateError(str(error)) from error

    def _read(self) -> dict[str, str]:
        document: JsonObject | None = read_json_object(self._file)
        stored: object = document.get(REPOS_KEY) if document else None
        if not isinstance(stored, dict):
            return {}
        return {key: value for key, value in stored.items() if isinstance(value, str)}
