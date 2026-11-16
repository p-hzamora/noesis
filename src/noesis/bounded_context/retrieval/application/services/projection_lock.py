"""Holding a projection's exclusive lock for the length of a block."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from noesis.exceptions import IndexSyncInProgressError

from ..ports.indexing.i_index_cursor_store import IIndexCursorStore

DEFAULT_LOCK_TTL_SECONDS: int = 300
POLL_INTERVAL_SECONDS: float = 0.25


@asynccontextmanager
async def projection_lock(
    cursors: IIndexCursorStore,
    *,
    projection: str,
    space_id: str,
    owner: str,
    wait_seconds: float,
    ttl_seconds: int,
) -> AsyncIterator[None]:
    """Acquire the lock (waiting up to `wait_seconds`), release it however the block ends.

    Raises:
        IndexSyncInProgressError: Another owner held the lock for the whole wait.
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
    try:
        yield
    finally:
        await cursors.release(projection, space_id, owner)
