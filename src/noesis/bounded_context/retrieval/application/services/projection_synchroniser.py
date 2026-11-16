"""Brings one projection up to date with Knowledge's change feed, under a lock the caller holds."""

from collections.abc import Sequence

from noesis.exceptions import IndexNotInitialisedError, IndexRebuildRequiredError
from noesis.shared_kernel.contracts.knowledge import (
    IndexableRecordContract,
    RecordBodyMissingError,
    RecordChangedContract,
    RecordStateContract,
)

from ...domain.value_objects import ProjectionKey
from ..dtos.index_dtos import ProjectionSyncDto
from ..ports.indexing.i_index_cursor_store import IIndexCursorStore
from ..ports.indexing.i_index_writer import IIndexWriter, ProjectionEntryDto
from ..ports.record_source.i_indexable_record_reader import IIndexableRecordReader
from ..ports.record_source.i_record_change_feed import IRecordChangeFeed
from ..ports.record_source.i_record_state_reader import IRecordStateReader

BATCH_SIZE: int = 100
INDEXABLE_TYPES: frozenset[str] = frozenset({"knowledge", "experience"})


class ProjectionSynchroniser:
    """Applies feed changes and single record states to a projection.

    The caller holds the projection's lock. Writes are idempotent upserts by record, so a crash
    mid-batch is repaired by re-applying the batch (the cursor moves after each batch).
    """

    def __init__(
        self,
        *,
        cursors: IIndexCursorStore,
        feed: IRecordChangeFeed,
        states: IRecordStateReader,
        indexables: IIndexableRecordReader,
    ) -> None:
        self._cursors: IIndexCursorStore = cursors
        self._feed: IRecordChangeFeed = feed
        self._states: IRecordStateReader = states
        self._indexables: IIndexableRecordReader = indexables

    async def sync(self, writer: IIndexWriter, *, space_id: str) -> ProjectionSyncDto:
        """Pull and apply every change after the cursor, up to the head read now.

        Raises:
            IndexNotInitialisedError: The projection has no cursor.
            IndexRebuildRequiredError: The cursor is ahead of the head or meets a gap.
        """
        kind: str = writer.kind
        cursor: int | None = await self._cursors.get(kind, space_id)
        if cursor is None:
            raise IndexNotInitialisedError(
                f"The {kind} index was never built for this space.",
                {"projection": kind, "space_id": space_id},
                next_steps=["Run `noesis index rebuild --yes`."],
            )
        head: int = await self._feed.head_sequence(space_id)
        if cursor > head:
            raise _rebuild_required(kind, f"its cursor {cursor} is ahead of the head {head}")
        applied: int = 0
        skipped: int = 0
        unknown: int = 0
        while cursor < head:
            batch: list[RecordChangedContract] = await self._feed.changes_after(
                cursor, space_id=space_id, limit=BATCH_SIZE
            )
            expected: int = cursor + 1
            for change in batch:
                if change.sequence != expected:
                    raise _rebuild_required(kind, f"change {expected} is missing from the feed")
                expected += 1
            if not batch:
                raise _rebuild_required(kind, f"change {cursor + 1} is missing from the feed")
            unknown += sum(
                change.change_kind not in {"created", "revised", "status_changed"}
                for change in batch
            )
            batch_applied, batch_skipped = await self._apply(writer, batch, space_id=space_id)
            applied += batch_applied
            skipped += batch_skipped
            cursor = batch[-1].sequence
            await self._cursors.advance(kind, space_id, cursor)
        return ProjectionSyncDto(
            kind=kind, applied=applied, skipped=skipped, cursor=cursor, unknown_changes=unknown
        )

    async def index_state(
        self, writer: IIndexWriter, state: RecordStateContract, *, space_id: str
    ) -> bool:
        """Upsert the record at its head revision; False when it is not indexable."""
        if state.record_type not in INDEXABLE_TYPES:
            return False
        try:
            record: IndexableRecordContract = await self._indexables.get(
                state.record_id, state.head_revision, space_id=space_id
            )
        except RecordBodyMissingError:
            return False
        await writer.upsert(
            ProjectionEntryDto(
                key=ProjectionKey(record_id=state.record_id, revision=state.head_revision),
                space_id=space_id,
                record=record,
            )
        )
        return True

    async def _apply(
        self, writer: IIndexWriter, batch: Sequence[RecordChangedContract], *, space_id: str
    ) -> tuple[int, int]:
        """Index each distinct record of the batch once; count changes applied and skipped."""
        known = [
            change
            for change in batch
            if change.change_kind in {"created", "revised", "status_changed"}
        ]
        if not known:
            return 0, len(batch)
        record_ids: list[str] = list(dict.fromkeys(change.record_id for change in known))
        found: dict[str, RecordStateContract] = {
            state.record_id: state
            for state in await self._states.get_states(record_ids, space_id=space_id)
        }
        indexed: dict[str, bool] = {}
        for record_id in record_ids:
            state: RecordStateContract | None = found.get(record_id)
            indexed[record_id] = state is not None and await self.index_state(
                writer, state, space_id=space_id
            )
        applied: int = sum(1 for change in known if indexed[change.record_id])
        return applied, len(batch) - applied


def _rebuild_required(kind: str, reason: str) -> IndexRebuildRequiredError:
    return IndexRebuildRequiredError(
        f"The {kind} index must be rebuilt: {reason}.",
        {"projection": kind, "reason": reason},
        next_steps=["Run `noesis index rebuild --yes`."],
    )
