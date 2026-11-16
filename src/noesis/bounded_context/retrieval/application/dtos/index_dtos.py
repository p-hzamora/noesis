"""Results of the index commands."""

from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class ProjectionSyncDto(FrozenObject):
    """One projection after a sync.

    Attributes:
        kind: The projection.
        applied: Changes applied.
        skipped: Changes skipped (other record types, ids not found, bodies missing).
        cursor: The cursor after the sync.
    """

    kind: str
    applied: int
    skipped: int
    unknown_changes: int = 0
    cursor: int


class SyncIndexResultDto(FrozenObject):
    """Result of `index sync`.

    Attributes:
        head_sequence: The feed's head when the sync started.
        projections: One entry per registered projection.
        warnings: Plain-English notices.
    """

    head_sequence: int
    projections: tuple[ProjectionSyncDto, ...]
    warnings: tuple[str, ...] = ()


class ProjectionRebuildDto(FrozenObject):
    """One projection after a rebuild.

    Attributes:
        kind: The projection.
        records_indexed: Records written by the scan.
        duration_seconds: Time the rebuild took.
        cursor: The cursor after the closing sync.
    """

    kind: str
    records_indexed: int
    duration_seconds: float
    cursor: int


class RebuildIndexResultDto(FrozenObject):
    """Result of `index rebuild`.

    Attributes:
        head_sequence: The feed's head when the rebuild started.
        projections: One entry per rebuilt projection.
        warnings: Plain-English notices.
    """

    head_sequence: int
    projections: tuple[ProjectionRebuildDto, ...]
    warnings: tuple[str, ...] = ()


class DivergenceDto(FrozenObject):
    """A record whose projection entry differs from its head.

    Attributes:
        record_id: The record.
        expected_revision: The head revision; null for an Experience or an entry no record
            backs (extra).
        found_revision: The revision the projection holds; null when the entry is missing or
            belongs to an Experience.
    """

    record_id: str
    expected_revision: int | None
    found_revision: int | None


class ProjectionStatusDto(FrozenObject):
    """One projection's status.

    Attributes:
        kind: The projection.
        cursor: Its cursor.
        lag: `head_sequence - cursor`.
        profile: What it was built with.
        divergences: Entries that differ from the records (only with `verify`).
    """

    kind: str
    cursor: int
    lag: int
    profile: dict[str, JsonValue]
    divergences: tuple[DivergenceDto, ...] = ()


class IndexStatusResultDto(FrozenObject):
    """Result of `index status`.

    Attributes:
        head_sequence: The feed's head.
        projections: One entry per registered projection.
        warnings: Plain-English notices.
        divergences: Every projection's divergences together (only with `verify`).
    """

    head_sequence: int
    projections: tuple[ProjectionStatusDto, ...]
    warnings: tuple[str, ...] = ()
    divergences: tuple[DivergenceDto, ...] = ()
