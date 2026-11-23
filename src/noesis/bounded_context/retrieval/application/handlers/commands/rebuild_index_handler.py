"""Rebuild projections from the records' current state."""

import time
from collections.abc import Sequence

from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts.knowledge import RecordStateContract
from noesis.shared_kernel.contracts.ports.retrieval import (
    IIndexableRecordReader,
    IRecordChangeFeed,
    IRecordStateReader,
)
from noesis.utils import FrozenObject

from ...dtos.index_dtos import ProjectionRebuildDto, RebuildIndexResultDto
from ...ports.indexing.i_index_cursor_store import IIndexCursorStore
from ...ports.indexing.i_index_writer import IIndexWriter
from ...ports.indexing.i_staged_index_writer import IStagedIndexWriter
from ...services.projection_lock import DEFAULT_LOCK_TTL_SECONDS, projection_lock
from ...services.projection_synchroniser import BATCH_SIZE, ProjectionSynchroniser


class RebuildIndexCommand(FrozenObject):
    """Rebuild projections of a space.

    Attributes:
        space_id: The active space.
        projection: The one projection to rebuild; every registered one when null.
        owner: Identifies this process as the lock holder.
    """

    space_id: str
    projection: str | None = None
    owner: str


class RebuildIndexHandler(IHandler[RebuildIndexCommand, RebuildIndexResultDto]):
    """Per projection, under its lease: mark rebuilding, capture the head, clear, scan heads, set
    the cursor, catch up, then publish the built profile."""

    def __init__(
        self,
        *,
        writers: Sequence[IIndexWriter],
        cursors: IIndexCursorStore,
        feed: IRecordChangeFeed,
        states: IRecordStateReader,
        indexables: IIndexableRecordReader,
        lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> None:
        self._writers: tuple[IIndexWriter, ...] = tuple(writers)
        self._cursors: IIndexCursorStore = cursors
        self._feed: IRecordChangeFeed = feed
        self._states: IRecordStateReader = states
        self._lock_ttl_seconds: int = lock_ttl_seconds
        self._synchroniser: ProjectionSynchroniser = ProjectionSynchroniser(
            cursors=cursors, feed=feed, states=states, indexables=indexables
        )

    async def handle(self, action: RebuildIndexCommand) -> RebuildIndexResultDto:
        """Rebuild; with no projection registered, take no lock and write nothing.

        Raises:
            InvalidConfigurationError: `projection` names no registered projection.
            IndexSyncInProgressError: A lock is held by another owner.
        """
        head: int = await self._feed.head_sequence(action.space_id)
        if not self._writers:
            return RebuildIndexResultDto(
                head_sequence=head,
                projections=(),
                warnings=("no index projection registered; nothing to rebuild",),
            )
        writers: tuple[IIndexWriter, ...] = self._selected(action.projection)
        rebuilt: list[ProjectionRebuildDto] = []
        for writer in writers:
            async with projection_lock(
                self._cursors,
                projection=writer.kind,
                space_id=action.space_id,
                owner=action.owner,
                wait_seconds=0,
                ttl_seconds=self._lock_ttl_seconds,
            ):
                rebuilt.append(await self._rebuild(writer, action.space_id, action.owner))
        return RebuildIndexResultDto(head_sequence=head, projections=tuple(rebuilt))

    def _selected(self, projection: str | None) -> tuple[IIndexWriter, ...]:
        if projection is None:
            return self._writers
        chosen: tuple[IIndexWriter, ...] = tuple(w for w in self._writers if w.kind == projection)
        if not chosen:
            raise InvalidConfigurationError(
                f"No index projection named {projection!r} is registered.",
                {"projection": projection, "registered": [w.kind for w in self._writers]},
                next_steps=["Run `noesis index status` to list the registered projections."],
            )
        return chosen

    async def _rebuild(
        self, writer: IIndexWriter, space_id: str, owner: str
    ) -> ProjectionRebuildDto:
        """Q-207: the space is `rebuilding` (unqueryable) from before the clear until published.

        A crash anywhere leaves the `rebuilding` marker, so ordinary sync refuses the space and
        only a new rebuild recovers it; other spaces are untouched.
        """
        started: float = time.monotonic()
        await self._cursors.begin_rebuild(writer.kind, space_id, owner=owner)
        captured_head: int = await self._feed.head_sequence(space_id)
        if isinstance(writer, IStagedIndexWriter):
            await writer.clear_fenced(space_id, owner=owner)
        else:
            await writer.clear(space_id)
        indexed: int = 0
        after_id: str | None = None
        while True:
            page: list[RecordStateContract] = await self._states.scan_states(
                space_id, after_id=after_id, limit=BATCH_SIZE
            )
            for state in page:
                if await self._synchroniser.index_state(
                    writer, state, space_id=space_id, owner=owner
                ):
                    indexed += 1
            if len(page) < BATCH_SIZE:
                break
            after_id = page[-1].record_id
        await self._cursors.advance(writer.kind, space_id, captured_head, owner=owner)
        closing = await self._synchroniser.sync(
            writer, space_id=space_id, owner=owner, rebuilding=True
        )
        await self._cursors.complete_rebuild(
            writer.kind, space_id, owner=owner, profile=writer.profile()
        )
        return ProjectionRebuildDto(
            kind=writer.kind,
            records_indexed=indexed,
            duration_seconds=time.monotonic() - started,
            cursor=closing.cursor,
        )
