"""Holding a projection's exclusive, renewed lease for the length of a block."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from noesis.exceptions import (
    GraphStoreAuthenticationFailedError,
    GraphStoreBusyError,
    GraphStoreQueryFailedError,
    GraphStoreUnavailableError,
    IndexSyncInProgressError,
)

from ..ports.indexing.i_index_cursor_store import IIndexCursorStore

DEFAULT_LOCK_TTL_SECONDS: int = 300
MAX_HEARTBEAT_SECONDS: float = 30.0
POLL_INTERVAL_SECONDS: float = 0.25

STORE_FAILURES: Final[tuple[type[Exception], ...]] = (
    GraphStoreUnavailableError,
    GraphStoreBusyError,
    GraphStoreAuthenticationFailedError,
    GraphStoreQueryFailedError,
)
"""The typed store failures that end a lease's guarantees without ending the process."""

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class LeaseHeartbeat:
    """Renews a held lease every `interval` seconds until stopped or the lease is lost.

    Renewal never re-takes an expired lease: once a renewal fails, `lost` stays true and the
    fenced writes of the holder fail in their own transactions. A typed store failure counts
    as a lost lease; any other error also marks the lease lost, then propagates (a bug, not an
    outage).
    """

    def __init__(
        self,
        cursors: IIndexCursorStore,
        *,
        projection: str,
        space_id: str,
        owner: str,
        ttl_seconds: int,
    ) -> None:
        self._cursors: IIndexCursorStore = cursors
        self._projection: str = projection
        self._space_id: str = space_id
        self._owner: str = owner
        self._ttl_seconds: int = ttl_seconds
        self.interval: float = min(MAX_HEARTBEAT_SECONDS, ttl_seconds / 3)
        self.lost: bool = False

    async def beat(self) -> bool:
        """Renew once; False (and `lost`) when the lease is gone or the store failed.

        Raises:
            Exception: Anything but a typed store failure, after marking the lease lost.
        """
        try:
            renewed: bool = await self._cursors.renew(
                self._projection, self._space_id, self._owner, self._ttl_seconds
            )
        except STORE_FAILURES as error:
            _LOGGER.warning(
                "%s lease renewal failed (%s); treating the lease as lost",
                self._projection,
                type(error).__name__,
            )
            renewed = False
        except Exception:
            self.lost = True
            raise
        if not renewed:
            self.lost = True
        return renewed

    async def run(self) -> None:
        """Beat every `interval` until a renewal fails or the task is cancelled."""
        while not self.lost:
            await asyncio.sleep(self.interval)
            await self.beat()


@asynccontextmanager
async def projection_lock(
    cursors: IIndexCursorStore,
    *,
    projection: str,
    space_id: str,
    owner: str,
    wait_seconds: float,
    ttl_seconds: int,
) -> AsyncIterator[LeaseHeartbeat]:
    """Acquire the lease (waiting up to `wait_seconds`), renew it while the block runs, release.

    Raises:
        IndexSyncInProgressError: Another owner held the lock for the whole wait.
        Exception: A renewal failed with something other than a typed store failure (the
            lease is released first).
    """
    waited: float = 0.0
    while not await cursors.acquire(projection, space_id, owner, ttl_seconds):
        if waited >= wait_seconds:
            raise IndexSyncInProgressError(
                f"Another sync or rebuild holds the {projection} index lock.",
                {"projection": projection, "space_id": space_id},
                next_steps=["Retry, or run `noesis index status`."],
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
    heartbeat = LeaseHeartbeat(
        cursors, projection=projection, space_id=space_id, owner=owner, ttl_seconds=ttl_seconds
    )
    task: asyncio.Task[None] = asyncio.create_task(heartbeat.run())
    try:
        yield heartbeat
    finally:
        task.cancel()
        try:
            with contextlib.suppress(asyncio.CancelledError):
                await task  # an unexpected renewal error surfaces here
        finally:
            await cursors.release(projection, space_id, owner)


def lease_lost(projection: str, space_id: str) -> IndexSyncInProgressError:
    """The error a fenced write raises once its owner's lease is gone."""
    return IndexSyncInProgressError(
        f"The {projection} index lease was lost to another sync or rebuild; nothing was written.",
        {"projection": projection, "space_id": space_id, "reason": "lease_lost"},
        next_steps=["Retry, or run `noesis index status`."],
    )
