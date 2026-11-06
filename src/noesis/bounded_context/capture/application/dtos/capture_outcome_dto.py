"""Why a capture command ended the way it did."""

from enum import StrEnum

from noesis.shared_kernel.application.dtos import BaseDto


class CaptureOutcomeEnum(StrEnum):
    """Every way a record or flush can end; the value is what the journal shows.

    The set, by command:

    - enable: `enabled`, `already_enabled` (a repeat, quiet).
    - disable: `disabled`.
    - record a commit: `marked`; `already_pending` (the commit is already pending, for instance
      the same HEAD seen in a second worktree: a repeat, quiet like `already_enabled`);
      `no_new_commit`; `ambiguous_worktree`; `not_opted_in` (quiet); `not_in_repo`.
    - flush: `no_pending` (quiet), `debounced`, `trivial`, `trivial_dropped`,
      `transcript_unreadable`, `no_real_work`, `handed_over`, `handover_failed`,
      `handover_abandoned`.

    Journals are append-only files, so every value ever written stays valid when read back:
    entries are stored as plain strings, and old values (such as `already_pending` in journals
    written before it became quiet) are still listed by `capture runs`.
    """

    ENABLED = "enabled"
    ALREADY_ENABLED = "already_enabled"
    DISABLED = "disabled"
    NOT_OPTED_IN = "not_opted_in"
    NOT_IN_REPO = "not_in_repo"
    MARKED = "marked"
    ALREADY_PENDING = "already_pending"
    NO_NEW_COMMIT = "no_new_commit"
    AMBIGUOUS_WORKTREE = "ambiguous_worktree"
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
        return self in {
            CaptureOutcomeEnum.NOT_OPTED_IN,
            CaptureOutcomeEnum.NO_PENDING,
            CaptureOutcomeEnum.ALREADY_ENABLED,
            CaptureOutcomeEnum.ALREADY_PENDING,
        }


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
