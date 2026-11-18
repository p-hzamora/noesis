"""What `import run` (and its preview) reports."""

from pydantic import Field

from noesis.shared_kernel.application.dtos import BaseDto


class AmbiguousLinkDto(BaseDto):
    """An unresolved target with the paths the user can disambiguate."""

    target: str
    candidates: tuple[str, ...]


class UnresolvedRelationDto(BaseDto):
    """A `related` entry that created no edge, with the candidates when ambiguous."""

    classification: str
    target: str
    relation: str
    candidates: tuple[str, ...] = ()


class ImportNoteRowDto(BaseDto):
    """One note of a run, in path order.

    Attributes:
        path: Relative POSIX path of the note.
        outcome: `created`, `unchanged`, `changed_in_vault`, `revised`, `successor_proposed`,
            `skipped_empty` or `blocked`.
        record_id: The record created, revised or matched; for `skipped_empty` and interop-blocked
            notes the declared ULID when valid, else None.
        revision: Revision written, planned or matched.
        status: Status of the record.
        title: Mapped title, when the note was mapped.
        subtype: Mapped subtype, when the note was mapped.
        project_key: Mapped project key.
        tags: Tags including the origin tag.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion.
        reason: Block reason, or the reduced-behaviour note.
        detail: The error code behind `invalid_metadata`.
        warnings: Warnings of the note.
    """

    path: str
    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    title: str | None = None
    subtype: str | None = None
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    target_record_id: str | None = None
    assertion_id: str | None = None
    reason: str | None = None
    detail: str | None = None
    warnings: tuple[str, ...] = ()
    links: dict[str, int | str | None] = Field(default_factory=dict)
    ambiguous: tuple[AmbiguousLinkDto, ...] = ()
    relations: dict[str, int | str | None] = Field(default_factory=dict)
    unresolved_relations: tuple[UnresolvedRelationDto, ...] = ()


class ImportTotalsDto(BaseDto):
    """Disjoint counts that add up to `notes`."""

    notes: int = 0
    created: int = 0
    unchanged: int = 0
    changed_in_vault: int = 0
    revised: int = 0
    successor_proposed: int = 0
    skipped_empty: int = 0
    blocked: int = 0


class ImportWarningCountsDto(BaseDto):
    """Warnings over every note that reached the mapping step."""

    legacy_header: int = 0
    dropped_tag: int = 0
    ignored_field: int = 0


class VaultImportResultDto(BaseDto):
    """The report of one `import run`.

    Attributes:
        applied: False for a preview.
        update: Whether `--update` was given.
        vault_key: The key used in locators.
        totals: Counts per outcome.
        blocked_reasons: One count per block reason that occurred.
        warnings: Warning counts.
        sources_skipped: Header source entries that did not map.
        complete: True when no note is blocked.
        notes: One row per note.
        next_steps: Commands to run next.
    """

    links: dict[str, int] = Field(default_factory=dict)
    link_sets: dict[str, int] = Field(default_factory=dict)
    relations: dict[str, int] = Field(default_factory=dict)
    applied: bool
    update: bool
    vault_key: str
    totals: ImportTotalsDto
    blocked_reasons: dict[str, int]
    warnings: ImportWarningCountsDto
    sources_skipped: int
    complete: bool
    notes: tuple[ImportNoteRowDto, ...]
    next_steps: tuple[str, ...]
