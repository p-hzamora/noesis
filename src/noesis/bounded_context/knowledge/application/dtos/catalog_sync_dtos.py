"""What `catalog sync` reports per runtime."""

from noesis.bounded_context.knowledge.application.dtos.not_installed_dto import NotInstalledDto
from noesis.bounded_context.knowledge.application.dtos.runtime_enum import RuntimeEnum
from noesis.bounded_context.knowledge.application.dtos.unreadable_kind_dto import UnreadableKindDto
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class SyncedEntryDto(BaseDto):
    """An entry a sync registered or revised (or would, on a dry run).

    Attributes:
        kind: Entry kind.
        name: Entry name.
        manifest_digest: Manifest hash the revision rests on.
        entry_id: The entry; None on a dry run that would register it.
        revision: Revision written; None on a dry run.
    """

    kind: CatalogEntryKindEnum
    name: str
    manifest_digest: str
    entry_id: str | None = None
    revision: int | None = None


class SkippedArtifactDto(BaseDto):
    """An installed artifact a sync did not write.

    Attributes:
        kind: Artifact kind.
        name: Artifact name.
        reason: Why: `invalid_name`, `manifest_unreadable` or `write_conflict`.
    """

    kind: CatalogEntryKindEnum
    name: str
    reason: str


class SyncRuntimeDto(BaseDto):
    """The sync of one runtime.

    Attributes:
        runtime: The runtime.
        host: Machine observed.
        observed_at: ISO-8601 UTC time of the observation.
        registered: Entries created.
        revised: Entries that got a new revision.
        unchanged: How many installed artifacts already match their entry.
        not_installed: Entries with no installed match (kept, never deleted).
        skipped: Installed artifacts that were not written.
        unreadable_kinds: Kinds that could not be read.
    """

    runtime: RuntimeEnum
    host: str
    observed_at: str
    registered: tuple[SyncedEntryDto, ...] = ()
    revised: tuple[SyncedEntryDto, ...] = ()
    unchanged: int = 0
    not_installed: tuple[NotInstalledDto, ...] = ()
    skipped: tuple[SkippedArtifactDto, ...] = ()
    unreadable_kinds: tuple[UnreadableKindDto, ...] = ()


class SyncReportDto(BaseDto):
    """The outcome of `catalog sync`.

    Attributes:
        dry_run: True when nothing was written.
        runtimes: One block per synced runtime.
        next_steps: What to do about what was found.
    """

    dry_run: bool
    runtimes: tuple[SyncRuntimeDto, ...]
    next_steps: tuple[str, ...] = ()
