"""Unit of Work over one session's JSON file, holding the session's file lock while open."""

from pathlib import Path
from types import TracebackType
from typing import Self

from noesis.bounded_context.capture.application.ports.uow import ICaptureUnitOfWork
from noesis.bounded_context.capture.domain.repositories import ICaptureSessionRepository
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.exceptions import (
    CaptureStateError,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import FileLock

from .json_file_capture_session_repository_adapter import JsonFileCaptureSessionRepositoryAdapter


class JsonFileCaptureUnitOfWorkAdapter(ICaptureUnitOfWork):
    """Lock on enter; write staged changes on `commit`; discard and unlock on exit."""

    def __init__(
        self,
        repository: JsonFileCaptureSessionRepositoryAdapter,
        session_id: SessionId,
        *,
        lock_timeout_seconds: float,
    ) -> None:
        self._repository: JsonFileCaptureSessionRepositoryAdapter = repository
        lock_file: Path = repository.file(session_id).with_suffix(".lock")
        self._lock: FileLock = FileLock(lock_file, timeout_seconds=lock_timeout_seconds)

    @property
    def sessions(self) -> ICaptureSessionRepository:
        """The session repository of this unit of work."""
        return self._repository

    async def __aenter__(self) -> Self:
        """Take the session lock.

        Raises:
            CaptureStateError: The lock stayed taken longer than the timeout.
        """
        try:
            await self._lock.__aenter__()
        except TimeoutError as error:
            raise CaptureStateError(str(error)) from error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            await self.rollback()
        finally:
            await self._lock.__aexit__(exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        """Write the staged session."""
        self._repository.flush()

    async def rollback(self) -> None:
        """Drop the staged session."""
        self._repository.discard()
