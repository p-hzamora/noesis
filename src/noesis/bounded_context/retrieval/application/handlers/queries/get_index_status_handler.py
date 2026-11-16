"""Report each projection's cursor, lag and (optionally) divergences from the records."""

from collections.abc import Sequence

from noesis.exceptions import IndexNotInitialisedError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts.knowledge import RecordStateContract
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from ....domain.enums import BuildStateEnum
from ...dtos.index_dtos import DivergenceDto, IndexStatusResultDto, ProjectionStatusDto
from ...ports.embedding.i_semantic_runtime_probe import ISemanticRuntimeProbe
from ...ports.indexing.i_index_cursor_store import IIndexCursorStore, ProjectionManifestDto
from ...ports.indexing.i_index_writer import IIndexWriter
from ...ports.record_source.i_record_change_feed import IRecordChangeFeed
from ...ports.record_source.i_record_state_reader import IRecordStateReader
from ...services.projection_synchroniser import BATCH_SIZE, INDEXABLE_TYPES


class GetIndexStatusQuery(FrozenObject):
    """Status of the registered projections.

    Attributes:
        space_id: The active space.
        verify: Also compare every projection with the records.
    """

    space_id: str
    verify: bool = False


class GetIndexStatusHandler(IHandler[GetIndexStatusQuery, IndexStatusResultDto]):
    """Reads cursors and manifests and, with `verify`, scans record states; never writes or locks.

    The semantic probe reports mode, model and runtime without loading or starting anything.
    """

    def __init__(
        self,
        *,
        writers: Sequence[IIndexWriter],
        cursors: IIndexCursorStore,
        feed: IRecordChangeFeed,
        states: IRecordStateReader,
        semantic_probe: ISemanticRuntimeProbe | None = None,
    ) -> None:
        self._writers: tuple[IIndexWriter, ...] = tuple(writers)
        self._cursors: IIndexCursorStore = cursors
        self._feed: IRecordChangeFeed = feed
        self._states: IRecordStateReader = states
        self._semantic_probe: ISemanticRuntimeProbe | None = semantic_probe

    async def handle(self, action: GetIndexStatusQuery) -> IndexStatusResultDto:
        """Report the head and every projection.

        Raises:
            IndexNotInitialisedError: A registered projection has no cursor.
        """
        head: int = await self._feed.head_sequence(action.space_id)
        semantic: dict[str, JsonValue] | None = (
            await self._semantic_probe.diagnostics() if self._semantic_probe is not None else None
        )
        if not self._writers:
            return IndexStatusResultDto(
                head_sequence=head,
                projections=(),
                warnings=("no index projection registered",),
                semantic=semantic,
            )
        expected: dict[str, int | None] = (
            await self._head_revisions(action.space_id) if action.verify else {}
        )
        projections: list[ProjectionStatusDto] = []
        for writer in self._writers:
            cursor: int | None = await self._cursors.get(writer.kind, action.space_id)
            manifest: ProjectionManifestDto | None = await self._cursors.manifest(
                writer.kind, action.space_id
            )
            rebuilding: bool = manifest is not None and manifest.state is BuildStateEnum.REBUILDING
            if cursor is None and not rebuilding:
                raise IndexNotInitialisedError(
                    f"The {writer.kind} index was never built for this space.",
                    {"projection": writer.kind, "space_id": action.space_id},
                    next_steps=["Run `noesis index rebuild --yes`."],
                )
            divergences: tuple[DivergenceDto, ...] = ()
            if action.verify:
                divergences = _divergences(expected, await writer.entries(action.space_id))
            configured: dict[str, JsonValue] = writer.profile()
            built: dict[str, JsonValue] | None = manifest.profile if manifest else None
            projections.append(
                ProjectionStatusDto(
                    kind=writer.kind,
                    cursor=cursor or 0,
                    lag=head - (cursor or 0),
                    profile=built if built is not None else configured,
                    divergences=divergences,
                    build_state=manifest.state.value if manifest else None,
                    configured_profile=configured,
                    profile_matches=None if built is None else built == configured,
                )
            )
        return IndexStatusResultDto(
            head_sequence=head,
            projections=tuple(projections),
            divergences=tuple(
                divergence for projection in projections for divergence in projection.divergences
            ),
            semantic=semantic,
        )

    async def _head_revisions(self, space_id: str) -> dict[str, int | None]:
        """Record id to head revision of every indexable record of the space."""
        found: dict[str, int | None] = {}
        after_id: str | None = None
        while True:
            page: list[RecordStateContract] = await self._states.scan_states(
                space_id, after_id=after_id, limit=BATCH_SIZE
            )
            found.update(
                {
                    state.record_id: state.head_revision
                    for state in page
                    if state.record_type in INDEXABLE_TYPES
                }
            )
            if len(page) < BATCH_SIZE:
                return found
            after_id = page[-1].record_id


def _divergences(
    expected: dict[str, int | None], found: dict[str, int | None]
) -> tuple[DivergenceDto, ...]:
    """Missing, extra and wrong-revision entries, ordered by record id."""
    differing: list[DivergenceDto] = []
    for record_id in sorted(expected.keys() | found.keys()):
        if record_id in expected and record_id in found and expected[record_id] == found[record_id]:
            continue
        differing.append(
            DivergenceDto(
                record_id=record_id,
                expected_revision=expected.get(record_id),
                found_revision=found.get(record_id),
            )
        )
    return tuple(differing)
