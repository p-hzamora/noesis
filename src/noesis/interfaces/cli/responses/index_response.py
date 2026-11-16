"""`noesis index` output."""

from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


def _footer(head_sequence: int, warnings: tuple[str, ...]) -> list[str]:
    return [f"head sequence: {head_sequence}", *(f"warning: {warning}" for warning in warnings)]


class IndexSyncedProjectionResponse(FrozenObject):
    """One projection after a sync.

    Attributes:
        kind: The projection.
        applied: Changes applied.
        skipped: Changes skipped.
        cursor: Cursor after the sync.
    """

    kind: str
    applied: int
    skipped: int
    unknown_changes: int = 0
    cursor: int


class IndexSyncResponse(IRenderableResponse):
    """`noesis index sync`.

    Attributes:
        head_sequence: The change feed's head.
        projections: One entry per registered projection.
        warnings: Plain-English notices.
    """

    head_sequence: int
    projections: tuple[IndexSyncedProjectionResponse, ...]
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [
            f"{item.kind}: applied {item.applied}, skipped {item.skipped} (unknown {item.unknown_changes}), cursor {item.cursor}"
            for item in self.projections
        ]
        return "\n".join([*lines, *_footer(self.head_sequence, self.warnings)])


class IndexRebuiltProjectionResponse(FrozenObject):
    """One projection after a rebuild.

    Attributes:
        kind: The projection.
        records_indexed: Records written.
        duration_seconds: How long the rebuild took.
        cursor: Cursor after the closing sync.
    """

    kind: str
    records_indexed: int
    duration_seconds: float
    cursor: int


class IndexRebuildResponse(IRenderableResponse):
    """`noesis index rebuild`.

    Attributes:
        head_sequence: The change feed's head.
        projections: One entry per rebuilt projection.
        warnings: Plain-English notices.
    """

    head_sequence: int
    projections: tuple[IndexRebuiltProjectionResponse, ...]
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [
            f"{item.kind}: indexed {item.records_indexed} in {item.duration_seconds:.2f}s, "
            f"cursor {item.cursor}"
            for item in self.projections
        ]
        return "\n".join([*lines, *_footer(self.head_sequence, self.warnings)])


class IndexDivergenceResponse(FrozenObject):
    """A record whose projection entry differs from its head.

    Attributes:
        record_id: The record.
        expected_revision: The head revision, when it has one.
        found_revision: The revision the projection holds, when any.
    """

    record_id: str
    expected_revision: int | None = None
    found_revision: int | None = None


class IndexProjectionStatusResponse(FrozenObject):
    """One projection's status.

    Attributes:
        kind: The projection.
        cursor: Its cursor.
        lag: Changes it has yet to apply.
        profile: What it was built with.
        divergences: Entries that differ from the records (only with `--verify`).
    """

    kind: str
    cursor: int
    lag: int
    profile: dict[str, JsonValue]
    divergences: tuple[IndexDivergenceResponse, ...] = ()


class IndexStatusResponse(IRenderableResponse):
    """`noesis index status`.

    Attributes:
        head_sequence: The change feed's head.
        projections: One entry per registered projection.
        divergences: Every projection's divergences together (only with `--verify`).
        warnings: Plain-English notices.
    """

    head_sequence: int
    projections: tuple[IndexProjectionStatusResponse, ...]
    divergences: tuple[IndexDivergenceResponse, ...] = ()
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [
            f"{item.kind}: cursor {item.cursor}, lag {item.lag}" for item in self.projections
        ]
        lines += [
            f"divergent {item.record_id}: expected revision {item.expected_revision}, "
            f"found {item.found_revision}"
            for item in self.divergences
        ]
        return "\n".join([*lines, *_footer(self.head_sequence, self.warnings)])
