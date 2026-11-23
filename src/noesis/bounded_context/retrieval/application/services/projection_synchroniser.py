"""Brings one projection up to date with Knowledge's change feed, under a lease the caller holds."""

from collections.abc import Sequence
from typing import Any

from noesis.exceptions import (
    IndexNotInitialisedError,
    IndexRebuildRequiredError,
    IndexSyncInProgressError,
)
from noesis.shared_kernel.contracts.knowledge import (
    IndexableRecordContract,
    RecordBodyMissingError,
    RecordChangedContract,
    RecordStateContract,
)
from noesis.shared_kernel.contracts.ports.retrieval import (
    IIndexableRecordReader,
    IRecordChangeFeed,
    IRecordStateReader,
)

from ...domain.enums import BuildStateEnum
from ...domain.value_objects import ProjectionKey
from ..dtos.index_dtos import ProjectionSyncDto
from ..ports.indexing.i_index_cursor_store import IIndexCursorStore, ProjectionManifestDto
from ..ports.indexing.i_index_writer import IIndexWriter, ProjectionEntryDto
from ..ports.indexing.i_staged_index_writer import IStagedIndexWriter

BATCH_SIZE: int = 100
INDEXABLE_TYPES: frozenset[str] = frozenset({"knowledge", "experience", "catalog_entry"})
KNOWN_CHANGE_KINDS: frozenset[str] = frozenset({"created", "revised", "status_changed"})
HEAD_RETRIES: int = 1


class ProjectionSynchroniser:
    """Applies feed changes and single record states to a projection.

    The caller holds the projection's lease and passes its `owner`; a staged writer's writes and
    every cursor advance are fenced on it. Writes are idempotent replacements by record, so a
    crash mid-batch is repaired by re-applying the batch (the cursor moves after each batch).
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

    async def sync(
        self,
        writer: IIndexWriter,
        *,
        space_id: str,
        owner: str | None = None,
        rebuilding: bool = False,
    ) -> ProjectionSyncDto:
        """Pull and apply every change after the cursor, up to the head read now.

        An ordinary sync (`rebuilding` false) refuses a space whose last rebuild did not finish;
        the rebuild's own catch-up passes `rebuilding`.

        Raises:
            IndexNotInitialisedError: The projection has no cursor.
            IndexRebuildRequiredError: The cursor is ahead of the head or meets a gap, a rebuild
                did not finish.
            IndexSyncInProgressError: `owner` lost the lease, or a record kept changing while it
                was embedded; the cursor did not pass the batch.
        """
        kind: str = writer.kind
        if not rebuilding:
            await self.require_complete(writer, space_id=space_id)
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
            unknown += sum(change.change_kind not in KNOWN_CHANGE_KINDS for change in batch)
            batch_applied, batch_skipped = await self._apply(
                writer, batch, space_id=space_id, owner=owner
            )
            applied += batch_applied
            skipped += batch_skipped
            cursor = batch[-1].sequence
            await self._cursors.advance(kind, space_id, cursor, owner=owner)
        return ProjectionSyncDto(
            kind=kind, applied=applied, skipped=skipped, cursor=cursor, unknown_changes=unknown
        )

    async def require_complete(self, writer: IIndexWriter, *, space_id: str) -> None:
        """Refuse an ordinary sync of a space whose last rebuild did not finish.

        Raises:
            IndexRebuildRequiredError: The manifest says `rebuilding`.
        """
        manifest: ProjectionManifestDto | None = await self._cursors.manifest(writer.kind, space_id)
        if manifest is not None and manifest.state is BuildStateEnum.REBUILDING:
            raise _rebuild_required(writer.kind, "its last rebuild did not finish")

    async def index_state(
        self,
        writer: IIndexWriter,
        state: RecordStateContract,
        *,
        space_id: str,
        owner: str | None = None,
    ) -> bool:
        """Write the record at its head revision; False when it is not indexable.

        A staged writer with an `owner` prepares outside any transaction, re-reads the head and
        commits only an entry of the current head: one retry on a moved head, then the batch is
        refused so the cursor does not pass it.

        Raises:
            IndexSyncInProgressError: The head moved again during the retry.
        """
        if isinstance(writer, IStagedIndexWriter) and owner is not None:
            return await self._index_staged(writer, state, space_id=space_id, owner=owner)
        entry: ProjectionEntryDto | None = await self._entry(state, space_id=space_id)
        if entry is None:
            return False
        await writer.upsert(entry)
        return True

    async def _index_staged(
        self,
        writer: IStagedIndexWriter[Any],
        state: RecordStateContract,
        *,
        space_id: str,
        owner: str,
    ) -> bool:
        current: RecordStateContract = state
        for _ in range(HEAD_RETRIES + 1):
            entry: ProjectionEntryDto | None = await self._entry(current, space_id=space_id)
            if entry is None:
                return False
            prepared: Any = await writer.prepare(entry)
            live: list[RecordStateContract] = await self._states.get_states(
                [current.record_id], space_id=space_id
            )
            if not live:
                return False
            if live[0].head_revision == current.head_revision:
                await writer.commit(prepared, owner=owner)
                return True
            current = live[0]
        raise IndexSyncInProgressError(
            f"Record {state.record_id} kept changing while the {writer.kind} index embedded it;"
            " the batch was not applied.",
            {"projection": writer.kind, "record_id": state.record_id, "reason": "head_churn"},
            next_steps=["Run `noesis index sync` again once the record settles."],
        )

    async def _entry(
        self, state: RecordStateContract, *, space_id: str
    ) -> ProjectionEntryDto | None:
        if state.record_type not in INDEXABLE_TYPES:
            return None
        try:
            record: IndexableRecordContract = await self._indexables.get(
                state.record_id, state.head_revision, space_id=space_id
            )
        except RecordBodyMissingError:
            return None
        return ProjectionEntryDto(
            key=ProjectionKey(record_id=state.record_id, revision=state.head_revision),
            space_id=space_id,
            record=record,
        )

    async def _apply(
        self,
        writer: IIndexWriter,
        batch: Sequence[RecordChangedContract],
        *,
        space_id: str,
        owner: str | None,
    ) -> tuple[int, int]:
        """Index each distinct record of the batch once; count changes applied and skipped."""
        known = [change for change in batch if change.change_kind in KNOWN_CHANGE_KINDS]
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
                writer, state, space_id=space_id, owner=owner
            )
        applied: int = sum(1 for change in known if indexed[change.record_id])
        return applied, len(batch) - applied


def _rebuild_required(kind: str, reason: str) -> IndexRebuildRequiredError:
    return IndexRebuildRequiredError(
        f"The {kind} index must be rebuilt: {reason}.",
        {"projection": kind, "reason": reason},
        next_steps=["Run `noesis index rebuild --yes`."],
    )
