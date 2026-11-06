"""`ICaptureSessionTreeReader` scanning the session files for parent links."""

from pathlib import Path

from noesis.bounded_context.capture.application.ports.read_repositories import (
    ICaptureSessionTreeReader,
)
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.infrastructure.outbound.persistence import read_json_object


class JsonFileCaptureSessionTreeReaderAdapter(ICaptureSessionTreeReader):
    """Reads `parent_id` straight from `<folder>/*.json`; it never writes or locks."""

    def __init__(self, folder: Path) -> None:
        self._folder: Path = folder

    async def children_of(self, session_id: SessionId) -> list[SessionId]:
        """Sessions whose stored `parent_id` is `session_id`, sorted by id."""
        children: list[SessionId] = []
        for file in sorted(self._folder.glob("*.json")):
            document = read_json_object(file)
            child: object = document.get("session_id") if document else None
            if (
                document
                and document.get("parent_id") == session_id.value
                and isinstance(child, str)
            ):
                children.append(SessionId(value=child))
        return children
