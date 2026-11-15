"""What `import file` reports."""

from noesis.shared_kernel.application.dtos import BaseDto


class ImportFileResultDto(BaseDto):
    """The result of registering one file.

    Attributes:
        applied: False for a dry run.
        path: The resolved absolute path.
        source_locator: The locator recorded for the file.
        outcome: `created`, `unchanged`, `revised` or `successor_proposed`.
        record_id: The record created, revised or matched.
        revision: Revision written, planned or matched.
        status: Status of the record.
        title: Mapped title.
        subtype: Mapped subtype.
        project_key: Mapped project key.
        tags: Tags including `origin:imported`.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion.
        reason: The reduced-behaviour note.
        warnings: Warnings of the file.
        next_steps: Commands to run next.
    """

    applied: bool
    path: str
    source_locator: str
    outcome: str
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    title: str
    subtype: str
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    target_record_id: str | None = None
    assertion_id: str | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
