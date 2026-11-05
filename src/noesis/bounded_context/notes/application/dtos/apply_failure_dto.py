"""What a failed apply keeps and reports."""

from noesis.shared_kernel.application.dtos import BaseDto


class RejectedEntryDto(BaseDto):
    """One entry of an apply payload that cannot be stored as written.

    Attributes:
        index: Position in the payload's `decisions`; None when the whole payload is unusable.
        reason: Why it was rejected.
    """

    index: int | None
    reason: str


class ApplyFailureRecordDto(BaseDto):
    """Where a failed apply was kept.

    Attributes:
        ticket: Id of the record.
        path: File that holds the record (errors and context).
        payload_path: File that holds the payload exactly as received, ready for `notes apply`.
    """

    ticket: str
    path: str
    payload_path: str
