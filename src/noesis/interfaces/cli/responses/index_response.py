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
        profile: What it was built with (the persisted build profile when one exists).
        divergences: Entries that differ from the records (only with `--verify`).
        build_state: `rebuilding` or `complete`; null when the projection records none.
        configured_profile: What it is configured with now.
        profile_matches: Whether the built profile equals the configured one.
    """

    kind: str
    cursor: int
    lag: int
    profile: dict[str, JsonValue]
    divergences: tuple[IndexDivergenceResponse, ...] = ()
    build_state: str | None = None
    configured_profile: dict[str, JsonValue] | None = None
    profile_matches: bool | None = None


class IndexStatusResponse(IRenderableResponse):
    """`noesis index status`.

    Attributes:
        head_sequence: The change feed's head.
        projections: One entry per registered projection.
        divergences: Every projection's divergences together (only with `--verify`).
        warnings: Plain-English notices.
        semantic: Semantic mode, dependency, model, runtime and vector index diagnostics.
    """

    head_sequence: int
    projections: tuple[IndexProjectionStatusResponse, ...]
    divergences: tuple[IndexDivergenceResponse, ...] = ()
    warnings: tuple[str, ...] = ()
    semantic: dict[str, JsonValue] | None = None

    def render(self) -> str:
        lines: list[str] = [
            f"{item.kind}: cursor {item.cursor}, lag {item.lag}"
            + (f", {item.build_state}" if item.build_state else "")
            + ("" if item.profile_matches in (None, True) else ", profile differs: rebuild")
            for item in self.projections
        ]
        if self.semantic is not None:
            lines.append(
                f"semantic: {self.semantic.get('state')} (mode {self.semantic.get('mode')}, "
                f"runtime {self.semantic.get('runtime')})"
            )
            if self.semantic.get("next_step"):
                lines.append(f"  next: {self.semantic['next_step']}")
        lines += [
            f"divergent {item.record_id}: expected revision {item.expected_revision}, "
            f"found {item.found_revision}"
            for item in self.divergences
        ]
        return "\n".join([*lines, *_footer(self.head_sequence, self.warnings)])


class ModelPrepareResponse(IRenderableResponse):
    """`noesis index model prepare`.

    Attributes:
        model: Model name.
        revision: Pinned upstream revision.
        licence: Model licence.
        directory: Where the files are.
        size_bytes: Bytes of every file.
        downloaded: Whether this call downloaded them (false: already prepared and verified).
        files: File name to SHA-256.
    """

    model: str
    revision: str
    licence: str
    directory: str
    size_bytes: int
    downloaded: bool
    files: dict[str, str]

    def render(self) -> str:
        verb: str = "downloaded and verified" if self.downloaded else "already prepared, verified"
        return (
            f"{self.model}@{self.revision[:12]} ({self.licence}): {verb}, "
            f"{self.size_bytes / 1_000_000:.1f} MB in {self.directory}"
        )


class EmbedderServeResponse(IRenderableResponse):
    """`noesis index embedder serve`, after it stopped.

    Attributes:
        socket: The socket it listened on (removed on stop).
        profile_hash: The profile it served.
    """

    socket: str
    profile_hash: str

    def render(self) -> str:
        return f"embedder stopped; socket {self.socket} removed"
