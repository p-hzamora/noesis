"""The CaptureSession aggregate: one agent session switched on for capture."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from noesis.bounded_context.capture.domain.value_objects import (
    CaptureModeEnum,
    CommitRecord,
    DiffSize,
    SessionId,
    TranscriptCursor,
)
from noesis.exceptions import (
    CaptureNotEnabledError,
)
from noesis.shared_kernel.domain.entities import AggregateRoot
from noesis.shared_kernel.domain.events import DomainEvent

MAX_FAILED_HANDOVERS: int = 2
"""A hand-over that cannot start is retried at the next turn end once, then abandoned."""


class CommitRecorded(DomainEvent["CaptureSession"]):
    """A commit joined the pending work."""


class WorkHandedOver(DomainEvent["CaptureSession"]):
    """The pending work was handed over as a work brief."""


class HandoverAbandoned(DomainEvent["CaptureSession"]):
    """The pending work was dropped after repeated hand-over failures."""


@dataclass(slots=True, kw_only=True)
class CaptureSession(AggregateRoot["CaptureSession"]):
    """Opt-in state, pending commits, and transcript progress of one session.

    Invariants: commits are recorded only while enabled, never twice, and all pending
    commits belong to one repository (a commit elsewhere starts a new batch).

    Attributes:
        id: The agent session.
        enabled: Whether the user switched capture on.
        mode: What a hand-over does.
        repository_path: Repository root of the pending commits.
        pending: Commits waiting for the next hand-over, oldest first.
        cursor: Transcript progress at the last hand-over.
        failed_handovers: Consecutive hand-overs that could not start.
    """

    id: SessionId
    enabled: bool = False
    mode: CaptureModeEnum = CaptureModeEnum.LIVE
    repository_path: str | None = None
    pending: tuple[CommitRecord, ...] = ()
    cursor: TranscriptCursor = field(default_factory=TranscriptCursor)
    failed_handovers: int = 0

    @classmethod
    def create(cls, session_id: SessionId, *, now: datetime) -> Self:
        """A new, switched-off session."""
        return cls(id=session_id, created_at=now, updated_at=now)

    @property
    def pending_size(self) -> DiffSize:
        """Summed size of the pending commits."""
        return sum((commit.size for commit in self.pending), DiffSize())

    def enable(self, mode: CaptureModeEnum, *, now: datetime) -> None:
        """Switch capture on in `mode`."""
        self.enabled = True
        self.mode = mode
        self.updated_at = now

    def disable(self, *, now: datetime) -> None:
        """Switch capture off; pending work is kept for when it is switched on again."""
        self.enabled = False
        self.updated_at = now

    def record_commit(self, commit: CommitRecord, *, repository_path: str, now: datetime) -> bool:
        """Add a finished commit to the pending work.

        Args:
            commit: The commit.
            repository_path: Root of the repository it belongs to.
            now: Current time.

        Returns:
            False when the commit was already pending.

        Raises:
            CaptureNotEnabledError: The session is switched off.
        """
        if not self.enabled:
            raise CaptureNotEnabledError(
                f"Capture is off for session {self.id}.", {"session_id": self.id.value}
            )
        if any(pending.sha == commit.sha for pending in self.pending):
            return False
        if self.repository_path not in (None, repository_path):
            self.pending = ()  # a different repository starts a new batch
        self.repository_path = repository_path
        self.pending = (*self.pending, commit)
        self.updated_at = now
        self._record(CommitRecorded(aggregate_id=self.id.value, payload={"sha": commit.sha}))
        return True

    def mark_handed_over(self, *, transcript_end: int, now: datetime) -> None:
        """The pending work left as a brief: clear it and move the transcript cursor."""
        handed: list[str] = [commit.sha for commit in self.pending]
        self.pending = ()
        self.failed_handovers = 0
        self.cursor = TranscriptCursor(offset=transcript_end, handed_over_at=now)
        self.updated_at = now
        self._record(WorkHandedOver(aggregate_id=self.id.value, payload={"commits": list(handed)}))

    def mark_handover_failed(self, *, final: bool, now: datetime) -> bool:
        """A hand-over could not start.

        Args:
            final: Whether this was the last chance (session end).
            now: Current time.

        Returns:
            True when the pending work was abandoned, False when it stays for one more try.
        """
        self.failed_handovers += 1
        self.updated_at = now
        if final or self.failed_handovers >= MAX_FAILED_HANDOVERS:
            dropped: list[str] = [commit.sha for commit in self.pending]
            self.pending = ()
            self.failed_handovers = 0
            self._record(
                HandoverAbandoned(aggregate_id=self.id.value, payload={"commits": list(dropped)})
            )
            return True
        return False

    def discard_pending(self, *, now: datetime) -> None:
        """Drop pending work that will never qualify (e.g. still trivial at session end)."""
        self.pending = ()
        self.updated_at = now
