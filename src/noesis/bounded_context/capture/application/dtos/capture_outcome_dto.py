"""Why a capture command ended the way it did."""

from enum import StrEnum

from noesis.shared_kernel.application.dtos import BaseDto


class CaptureOutcomeEnum(StrEnum):
    """Every way a record or flush can end; the value is what the journal shows."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    NOT_OPTED_IN = "not_opted_in"
    NOT_IN_REPO = "not_in_repo"
    MARKED = "marked"
    ALREADY_PENDING = "already_pending"
    NO_PENDING = "no_pending"
    DEBOUNCED = "debounced"
    TRIVIAL = "trivial"
    TRIVIAL_DROPPED = "trivial_dropped"
    TRANSCRIPT_UNREADABLE = "transcript_unreadable"
    NO_REAL_WORK = "no_real_work"
    HANDED_OVER = "handed_over"
    HANDOVER_FAILED = "handover_failed"
    HANDOVER_ABANDONED = "handover_abandoned"

    @property
    def is_quiet(self) -> bool:
        """Outcomes of nearly every turn; journaled only in trace mode."""
        return self in {CaptureOutcomeEnum.NOT_OPTED_IN, CaptureOutcomeEnum.NO_PENDING}


class CaptureOutcomeDto(BaseDto):
    """Result of a record or flush.

    Attributes:
        session_id: The session.
        outcome: What happened.
        detail: Human detail (commit subject, brief file, failure reason).
    """

    session_id: str
    outcome: CaptureOutcomeEnum
    detail: str = ""
