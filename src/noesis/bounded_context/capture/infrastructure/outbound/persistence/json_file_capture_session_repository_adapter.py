"""`ICaptureSessionRepository` storing one JSON file per session."""

from pathlib import Path

from pydantic import ValidationError

from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.repositories import ICaptureSessionRepository
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.exceptions import (
    CaptureStateError,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import (
    read_json_object,
    write_json_atomic,
)

from .mappers import CaptureSessionMapper


class JsonFileCaptureSessionRepositoryAdapter(ICaptureSessionRepository):
    """Sessions live in `<folder>/<session id>.json`; `save` stages until `flush`."""

    def __init__(self, folder: Path, mapper: CaptureSessionMapper) -> None:
        self._folder: Path = folder
        self._mapper: CaptureSessionMapper = mapper
        self._staged: dict[str, CaptureSession] = {}

    def file(self, session_id: SessionId) -> Path:
        """Where the session is stored."""
        return self._folder / f"{session_id.value}.json"

    async def get(self, session_id: SessionId) -> CaptureSession | None:
        """The staged or stored session.

        Raises:
            CaptureStateError: The stored file is corrupt.
        """
        if session_id.value in self._staged:
            return self._staged[session_id.value]
        document: JsonObject | None = read_json_object(self.file(session_id))
        if document is None:
            return None
        try:
            return self._mapper.to_entity(document)
        except ValidationError as error:
            raise CaptureStateError(
                f"Capture state of {session_id} is corrupt.",
                {"file": str(self.file(session_id))},
                next_steps=[f"Delete {self.file(session_id)} and switch capture on again."],
            ) from error

    async def save(self, session: CaptureSession) -> None:
        """Stage `session` for the next flush."""
        self._staged[session.id.value] = session

    def flush(self) -> None:
        """Write the staged sessions atomically."""
        for session in self._staged.values():
            write_json_atomic(self.file(session.id), self._mapper.to_document(session))
        self._staged.clear()

    def discard(self) -> None:
        """Forget staged sessions."""
        self._staged.clear()
