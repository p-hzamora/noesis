"""What an import of one note did, or would do."""

from noesis.shared_kernel.application.dtos import BaseDto


class ImportKnowledgeResultDto(BaseDto):
    """The outcome of applying or assessing one import request.

    Attributes:
        outcome: `created`, `unchanged`, `changed`, `revised`, `successor_proposed`, `blocked`.
        record_id: The record created, revised or matched; None for a planned create without a
            given id and for a block before a target is known.
        revision: Revision written or planned; the head for `unchanged` and `changed`.
        status: Status of `record_id`.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion (apply only).
        block_reason: Why the outcome is `blocked`.
        reason: Note of a successor created without assertions.
        replayed: True when the result came from the idempotency ledger.
    """

    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    target_record_id: str | None = None
    assertion_id: str | None = None
    block_reason: str | None = None
    reason: str | None = None
    replayed: bool = False
