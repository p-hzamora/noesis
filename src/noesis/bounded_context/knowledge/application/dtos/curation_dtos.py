"""DTOs of the curation module: related records, a curation result, parked tickets."""

from noesis.shared_kernel.application.dtos import BaseDto


class RelatedRecordDto(BaseDto):
    """An existing record found for a brief, as the curator sees it.

    There is no ownership and no marker for records migrated by C3: a related record is a
    record (FR-013).

    Attributes:
        record_id: The record's id.
        record_type: `knowledge` or `experience`.
        subtype: Its subtype.
        title: Its head title (knowledge), or the lookup's title.
        status: Its status; None for an experience.
        project_key: Its project key; None when space-wide.
        revision: Its head revision; None for an experience.
    """

    record_id: str
    record_type: str
    subtype: str | None = None
    title: str | None = None
    status: str | None = None
    project_key: str | None = None
    revision: int | None = None


class CurationItemDto(BaseDto):
    """What one candidate became.

    Attributes:
        ordinal: Its position in the plan, from 1.
        candidate: Its local key (`#<ordinal>` when it had none).
        kind: `experience`, `knowledge` or `skip`; None when unreadable.
        outcome: `recorded`, `proposed`, `revised`, `successor_proposed` or `skipped`.
        record_id: The record written or revised; None when skipped or on a dry run.
        type: Its record type; None when skipped.
        revision: Its head revision after the write; None for an experience, a skip or a dry run.
        status: Its status; None for an experience, a skip or a dry run.
        target_record_id: The record the candidate named; None when none.
        assertion_ids: Assertions proposed for it (`supersedes`, `supports`).
        reason: Why it was skipped, or a reduced-behaviour note; None otherwise.
    """

    ordinal: int
    candidate: str
    kind: str | None = None
    outcome: str
    record_id: str | None = None
    type: str | None = None
    revision: int | None = None
    status: str | None = None
    target_record_id: str | None = None
    assertion_ids: tuple[str, ...] = ()
    reason: str | None = None


class CurationSourceDto(BaseDto):
    """A source cited by every write of a submission.

    Attributes:
        id: Its id; None when not stored (a dry run, or nothing was written for it).
        kind: `work_brief`, `commit` or `agent_session`.
        locator: Its locator.
    """

    id: str | None = None
    kind: str
    locator: str


class RelatedLookupDto(BaseDto):
    """How the related lookup went.

    Attributes:
        state: `used` or `disabled`.
        pending_changes: The index lag the lookup reported; None when disabled.
    """

    state: str
    pending_changes: int | None = None


class CurationResultDto(BaseDto):
    """The outcome of `curate brief`, `curate apply` and `curate retry`.

    Attributes:
        ticket: The inbox ticket; None on a dry run.
        submission_key: The submission's key.
        dry_run: True when nothing was written.
        replayed: True when the plan was registered before this invocation.
        items: One per candidate, in plan order.
        sources: The sources of every write.
        related_lookup: How the related lookup went.
    """

    ticket: str | None = None
    submission_key: str
    dry_run: bool = False
    replayed: bool = False
    items: tuple[CurationItemDto, ...] = ()
    sources: tuple[CurationSourceDto, ...] = ()
    related_lookup: RelatedLookupDto


class RejectedEntryDto(BaseDto):
    """An entry of an apply payload that cannot be used.

    Attributes:
        index: Its position in the payload; None when the payload as a whole is unusable.
        reason: What is wrong with it.
    """

    index: int | None = None
    reason: str


class PlanRegistrationDto(BaseDto):
    """The registration of a plan in the ledger.

    Attributes:
        source_id: The id of the `work_brief` Source the registration ensured.
        replayed: True when the plan was already registered.
    """

    source_id: str
    replayed: bool = False


class ParkedCurationDto(BaseDto):
    """One parked ticket.

    Attributes:
        ticket: The ticket to pass to `curate retry`.
        stage: The stage it failed at; a retry returns to it.
        reason: Why it failed.
        repository: The project key of the submission.
        parked_at: ISO time of the last failure.
        age_seconds: Seconds since then.
    """

    ticket: str
    stage: str
    reason: str
    repository: str
    parked_at: str
    age_seconds: int
