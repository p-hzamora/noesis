"""Result of remembering a record: the capture result plus reconciliation and assertions."""

from noesis.shared_kernel.application.dtos import BaseDto


class ReconciledRecordDto(BaseDto):
    """An existing record found alike the one being remembered.

    Attributes:
        id: The existing record's id.
        score: Lexical overlap with the new text, 0..1.
        authority: Its authority tier (`authoritative`, `proposed`, `experience`, ...).
        title: Its title; None for an experience.
    """

    id: str
    score: float
    authority: str
    title: str | None = None


class ReconciliationDto(BaseDto):
    """What the space already holds that resembles the new record; nothing here is merged.

    Attributes:
        duplicates: Records at or above the duplicate threshold, best first.
        related: Records at or above the related threshold, best first.
        warnings: Why the lookup was partial or skipped, when it was.
    """

    duplicates: tuple[ReconciledRecordDto, ...] = ()
    related: tuple[ReconciledRecordDto, ...] = ()
    warnings: tuple[str, ...] = ()


class RememberedAssertionDto(BaseDto):
    """A `refines` or `supersedes` assertion the request asked for.

    Attributes:
        id: The assertion id; None for a preview or a failed proposal.
        predicate: `refines` or `supersedes`.
        object_ref: The target as the caller wrote it.
        status: `proposed`, `planned` (preview) or `failed`.
        error: Error code and message of a failed proposal.
    """

    id: str | None = None
    predicate: str
    object_ref: str
    status: str
    error: str | None = None


class RememberResultDto(BaseDto):
    """The record remember wrote (or would write) and what surrounds it.

    Attributes:
        written: False for a preview; nothing was written.
        record_id: The record's id; None for a preview.
        record_type: `knowledge` or `experience`.
        revision: Head revision (knowledge); None for an experience.
        status: `proposed` (knowledge); None for an experience.
        space_id: Space it lives in.
        project_id: Its project, when any.
        replayed: True when the idempotency key was already used and nothing was written.
        idempotency_key: The key used, given or derived.
        reconciliation: Duplicates and related records.
        assertions: The requested assertions.
        next_steps: What to do next.
    """

    written: bool
    record_id: str | None = None
    record_type: str
    revision: int | None = None
    status: str | None = None
    space_id: str
    project_id: str | None = None
    replayed: bool = False
    idempotency_key: str
    reconciliation: ReconciliationDto
    assertions: tuple[RememberedAssertionDto, ...] = ()
    next_steps: tuple[str, ...] = ()
