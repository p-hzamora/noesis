"""`IIndexCursorStore` over `:IndexCursor` nodes, with a compare-and-set lock that expires.

`:IndexCursor {cursor_key: "<projection>:<space_id>", projection, space_id, sequence,
lock_owner, lock_expires_at}`. The lock is taken in one transaction: the node is merged, its
write lock is taken with `SET c._lock = true REMOVE c._lock`, and only then are owner and expiry
read and set, so two racing acquirers are serialised and exactly one wins. Expiry is compared
against the injected clock, so a lock whose owner died is taken over after its TTL.
"""

from datetime import datetime, timedelta
from typing import Any, LiteralString

from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from ....application.ports.indexing.i_index_cursor_store import IIndexCursorStore

_GET: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
RETURN c.sequence AS sequence
"""

_ADVANCE: LiteralString = """
MERGE (c:IndexCursor {cursor_key: $cursor_key})
ON CREATE SET c.projection = $projection, c.space_id = $space_id
SET c.sequence = $sequence
"""

_TAKE_NODE_LOCK: LiteralString = """
MERGE (c:IndexCursor {cursor_key: $cursor_key})
ON CREATE SET c.projection = $projection, c.space_id = $space_id
SET c._lock = true
REMOVE c._lock
RETURN c.lock_owner AS owner, c.lock_expires_at AS expires_at
"""

_SET_OWNER: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c.lock_owner = $owner, c.lock_expires_at = $expires_at
"""

_RELEASE: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
WHERE c.lock_owner = $owner
REMOVE c.lock_owner, c.lock_expires_at
"""


class Neo4jIndexCursorStoreAdapter(IIndexCursorStore):
    """Cursors and locks of projections, each call in its own transaction.

    Args:
        client: The shared Neo4j client.
        clock: Source of "now" for lock expiry.
    """

    def __init__(self, client: Neo4jClient, clock: IClock) -> None:
        self._client: Neo4jClient = client
        self._clock: IClock = clock

    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor; null when the node does not exist or holds only a lock."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _GET, {"cursor_key": _key(projection, space_id)}
            )
        return None if not rows or rows[0]["sequence"] is None else int(rows[0]["sequence"])

    async def advance(self, projection: str, space_id: str, sequence: int) -> None:
        """Set the cursor, creating the node when needed."""
        async with await self._client.begin() as transaction:
            await transaction.run(
                _ADVANCE,
                {**_identity(projection, space_id), "sequence": sequence},
            )
            await transaction.commit()

    async def acquire(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Take the lock when it is free, expired, or already `owner`'s."""
        now: datetime = self._clock.now()
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _TAKE_NODE_LOCK, _identity(projection, space_id)
            )
            holder: str | None = rows[0]["owner"]
            expires_at: datetime | None = rows[0]["expires_at"]
            if (
                holder is not None
                and holder != owner
                and expires_at is not None
                and expires_at > now
            ):
                return False  # leaving the block rolls the transaction back
            await transaction.run(
                _SET_OWNER,
                {
                    "cursor_key": _key(projection, space_id),
                    "owner": owner,
                    "expires_at": now + timedelta(seconds=ttl_seconds),
                },
            )
            await transaction.commit()
        return True

    async def release(self, projection: str, space_id: str, owner: str) -> None:
        """Drop the lock when `owner` holds it."""
        async with await self._client.begin() as transaction:
            await transaction.run(
                _RELEASE, {"cursor_key": _key(projection, space_id), "owner": owner}
            )
            await transaction.commit()


def _key(projection: str, space_id: str) -> str:
    return f"{projection}:{space_id}"


def _identity(projection: str, space_id: str) -> dict[str, str]:
    return {
        "cursor_key": _key(projection, space_id),
        "projection": projection,
        "space_id": space_id,
    }
