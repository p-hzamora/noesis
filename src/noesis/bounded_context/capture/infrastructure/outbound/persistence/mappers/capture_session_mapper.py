"""Maps the CaptureSession aggregate to a JSON document (`to_document`) and back (`to_entity`)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import (
    CaptureModeEnum,
    CommitRecord,
    SessionId,
    TranscriptCursor,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)

DOCUMENT_VERSION: int = 1


class _CaptureSessionDocument(BaseModel):
    """Stored shape of a session (version 1)."""

    model_config = ConfigDict(extra="ignore")

    version: int = DOCUMENT_VERSION
    session_id: str
    enabled: bool
    mode: CaptureModeEnum
    repository_path: str | None
    pending: list[CommitRecord]
    cursor: TranscriptCursor
    failed_handovers: int
    created_at: datetime
    updated_at: datetime


class CaptureSessionMapper:
    """Translation between the aggregate and its stored JSON document."""

    def to_document(self, session: CaptureSession) -> JsonObject:
        """The JSON document of `session`."""
        document: _CaptureSessionDocument = _CaptureSessionDocument(
            session_id=session.id.value,
            enabled=session.enabled,
            mode=session.mode,
            repository_path=session.repository_path,
            pending=list(session.pending),
            cursor=session.cursor,
            failed_handovers=session.failed_handovers,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        return document.model_dump(mode="json")

    def to_entity(self, document: JsonObject) -> CaptureSession:
        """Rebuild the aggregate (no events are recorded on reconstitution)."""
        stored: _CaptureSessionDocument = _CaptureSessionDocument.model_validate(document)
        return CaptureSession(
            id=SessionId(value=stored.session_id),
            enabled=stored.enabled,
            mode=stored.mode,
            repository_path=stored.repository_path,
            pending=tuple(stored.pending),
            cursor=stored.cursor,
            failed_handovers=stored.failed_handovers,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )
