"""Assembler from the CaptureSession aggregate to its status DTO."""

from datetime import datetime

from noesis.bounded_context.capture.application.dtos import CaptureStatusDto
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId


class CaptureSessionAssembler:
    """`to_dto` turns a session (or its absence) into what `status` shows."""

    @staticmethod
    def to_dto(session: CaptureSession | None, session_id: SessionId) -> CaptureStatusDto:
        """Status of `session`; a missing session reads as switched off with nothing pending."""
        if session is None:
            return CaptureStatusDto(
                session_id=session_id.value,
                enabled=False,
                mode=CaptureModeEnum.LIVE.value,
                repository_path=None,
                pending_commits=0,
                pending_files=0,
                pending_lines=0,
                last_handover_at=None,
                failed_handovers=0,
            )
        handed_over: datetime | None = session.cursor.handed_over_at
        return CaptureStatusDto(
            session_id=session.id.value,
            enabled=session.enabled,
            mode=session.mode.value,
            repository_path=session.repository_path,
            pending_commits=len(session.pending),
            pending_files=session.pending_size.files,
            pending_lines=session.pending_size.lines,
            last_handover_at=handed_over.isoformat(timespec="seconds") if handed_over else None,
            failed_handovers=session.failed_handovers,
            repo_id=session.repo_id,
            parent_id=session.parent_id,
        )
