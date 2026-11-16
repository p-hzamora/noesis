"""Bring every registered projection up to date with the change feed."""

from collections.abc import Sequence

from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

from ...dtos.index_dtos import ProjectionSyncDto, SyncIndexResultDto
from ...ports.indexing.i_index_cursor_store import IIndexCursorStore
from ...ports.indexing.i_index_writer import IIndexWriter
from ...ports.record_source.i_indexable_record_reader import IIndexableRecordReader
from ...ports.record_source.i_record_change_feed import IRecordChangeFeed
from ...ports.record_source.i_record_state_reader import IRecordStateReader
from ...services.projection_lock import DEFAULT_LOCK_TTL_SECONDS, projection_lock
from ...services.projection_synchroniser import ProjectionSynchroniser


class SyncIndexCommand(FrozenObject):
    """Sync the registered projections of a space.

    Attributes:
        space_id: The active space.
        wait_seconds: How long to wait for a projection's lock.
        owner: Identifies this process as the lock holder.
    """

    space_id: str
    wait_seconds: int = 0
    owner: str


class SyncIndexHandler(IHandler[SyncIndexCommand, SyncIndexResultDto]):
    """Per projection: lock, read the cursor, apply the changes in batches, release."""

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
        self._lock_ttl_seconds: int = lock_ttl_seconds
        self._synchroniser: ProjectionSynchroniser = ProjectionSynchroniser(
            cursors=cursors, feed=feed, states=states, indexables=indexables
        )

    async def handle(self, action: SyncIndexCommand) -> SyncIndexResultDto:
        """Sync; with no projection registered, take no lock and write nothing.

        Raises:
            IndexSyncInProgressError: A lock was not obtained within the wait.
            IndexNotInitialisedError: A projection has no cursor.
            IndexRebuildRequiredError: A cursor is ahead of the head or meets a gap.
        """
        head: int = await self._feed.head_sequence(action.space_id)
        if not self._writers:
            return SyncIndexResultDto(
                head_sequence=head,
                projections=(),
                warnings=("no index projection registered; nothing to sync",),
            )
        synced: list[ProjectionSyncDto] = []
        for writer in self._writers:
            async with projection_lock(
                self._cursors,
                projection=writer.kind,
                space_id=action.space_id,
                owner=action.owner,
                wait_seconds=action.wait_seconds,
                ttl_seconds=self._lock_ttl_seconds,
            ):
                synced.append(await self._synchroniser.sync(writer, space_id=action.space_id))
        return SyncIndexResultDto(head_sequence=head, projections=tuple(synced))
