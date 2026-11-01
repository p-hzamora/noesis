"""State of one capture session."""

from noesis.shared_kernel.application.dtos import BaseDto


class CaptureStatusDto(BaseDto):
    """What `noesis capture status` shows.

    Attributes:
        session_id: The session.
        enabled: Whether capture is on.
        mode: `live` or `dry-run`.
        repository_path: Repository of the pending commits.
        pending_commits: Commits waiting for a hand-over.
        pending_files: Files they touch.
        pending_lines: Lines they change.
        last_handover_at: Time of the last hand-over (ISO), if any.
        failed_handovers: Consecutive hand-overs that could not start.
    """

    session_id: str
    enabled: bool
    mode: str
    repository_path: str | None
    pending_commits: int
    pending_files: int
    pending_lines: int
    last_handover_at: str | None
    failed_handovers: int
