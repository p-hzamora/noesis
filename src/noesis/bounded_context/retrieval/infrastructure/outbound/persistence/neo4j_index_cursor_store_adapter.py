"""`IIndexCursorStore` over `:IndexCursor` nodes: cursor, build manifest and a fenced lease.

`:IndexCursor {cursor_key: "<projection>:<space_id>", projection, space_id, sequence,
lock_owner, lock_expires_at, build_state, built_profile}`. Every lease check takes the node's
write lock first (`SET c._lock = true REMOVE c._lock`) and only then reads owner and expiry, so
racing acquirers, renewers and fenced writers are serialised. Expiry is compared against the
injected clock, so a lease whose owner died is taken over after its TTL, and a stale owner's
fenced writes fail even after a newer owner took the lease and released it.
"""

import json
from datetime import datetime, timedelta
from typing import Any, LiteralString

from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from ....application.ports.indexing.i_index_cursor_store import (
    IIndexCursorStore,
    ProjectionManifestDto,
)
from ....application.services.projection_lock import lease_lost
from ....domain.enums import BuildStateEnum

_GET: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
RETURN c.sequence AS sequence
"""

_MANIFEST: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
RETURN c.sequence AS sequence, c.build_state AS build_state, c.built_profile AS built_profile
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

FENCE: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c._lock = true
REMOVE c._lock
WITH c
WHERE c.lock_owner = $owner AND c.lock_expires_at > $now
RETURN c.cursor_key AS cursor_key
"""
"""Locks the cursor node and returns a row only while `$owner` holds the unexpired lease."""

_SET_OWNER: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c.lock_owner = $owner, c.lock_expires_at = $expires_at
"""

_SET_SEQUENCE: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c.sequence = $sequence
"""

_BEGIN_REBUILD: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c.build_state = 'rebuilding'
REMOVE c.built_profile
"""

_COMPLETE_REBUILD: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
SET c.build_state = 'complete', c.built_profile = $profile
"""

_RELEASE: LiteralString = """
MATCH (c:IndexCursor {cursor_key: $cursor_key})
WHERE c.lock_owner = $owner
REMOVE c.lock_owner, c.lock_expires_at
"""


class Neo4jIndexCursorStoreAdapter(IIndexCursorStore):
    """Cursors, manifests and leases of projections, each call in its own transaction.

    Args:
        client: The shared Neo4j client.
        clock: Source of "now" for lease expiry.
    """

    def __init__(self, client: Neo4jClient, clock: IClock) -> None:
        self._client: Neo4jClient = client
        self._clock: IClock = clock

    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor; null when the node does not exist or holds only a lock."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _GET, {"cursor_key": cursor_key(projection, space_id)}
            )
        return None if not rows or rows[0]["sequence"] is None else int(rows[0]["sequence"])

    async def advance(
        self, projection: str, space_id: str, sequence: int, *, owner: str | None = None
    ) -> None:
        """Set the cursor; with `owner`, fenced on the lease in the same transaction."""
        async with await self._client.begin() as transaction:
            if owner is None:
                await transaction.run(
                    _ADVANCE, {**_identity(projection, space_id), "sequence": sequence}
                )
            else:
                await self.fence(transaction, projection, space_id, owner)
                await transaction.run(
                    _SET_SEQUENCE,
                    {"cursor_key": cursor_key(projection, space_id), "sequence": sequence},
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
                    "cursor_key": cursor_key(projection, space_id),
                    "owner": owner,
                    "expires_at": now + timedelta(seconds=ttl_seconds),
                },
            )
            await transaction.commit()
        return True

    async def renew(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Extend the lease only while `owner` holds it unexpired."""
        now: datetime = self._clock.now()
        async with await self._client.begin() as transaction:
            held: list[dict[str, Any]] = await transaction.run(
                FENCE,
                {"cursor_key": cursor_key(projection, space_id), "owner": owner, "now": now},
            )
            if not held:
                return False
            await transaction.run(
                _SET_OWNER,
                {
                    "cursor_key": cursor_key(projection, space_id),
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
                _RELEASE, {"cursor_key": cursor_key(projection, space_id), "owner": owner}
            )
            await transaction.commit()

    async def manifest(self, projection: str, space_id: str) -> ProjectionManifestDto | None:
        """The build state and built profile; a pre-manifest cursor reads as complete."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _MANIFEST, {"cursor_key": cursor_key(projection, space_id)}
            )
        if not rows:
            return None
        row: dict[str, Any] = rows[0]
        if row["build_state"] is None:
            if row["sequence"] is None:
                return None
            return ProjectionManifestDto(state=BuildStateEnum.COMPLETE)
        profile: dict[str, JsonValue] | None = (
            json.loads(row["built_profile"]) if row["built_profile"] is not None else None
        )
        return ProjectionManifestDto(state=BuildStateEnum(row["build_state"]), profile=profile)

    async def begin_rebuild(self, projection: str, space_id: str, *, owner: str) -> None:
        """Mark `rebuilding` and drop the built profile, fenced on the lease."""
        async with await self._client.begin() as transaction:
            await self.fence(transaction, projection, space_id, owner)
            await transaction.run(_BEGIN_REBUILD, {"cursor_key": cursor_key(projection, space_id)})
            await transaction.commit()

    async def complete_rebuild(
        self,
        projection: str,
        space_id: str,
        *,
        owner: str,
        profile: dict[str, JsonValue],
    ) -> None:
        """Publish the built profile and `complete`, fenced on the lease."""
        async with await self._client.begin() as transaction:
            await self.fence(transaction, projection, space_id, owner)
            await transaction.run(
                _COMPLETE_REBUILD,
                {
                    "cursor_key": cursor_key(projection, space_id),
                    "profile": json.dumps(profile, sort_keys=True),
                },
            )
            await transaction.commit()

    async def fence(
        self, transaction: Neo4jTransaction, projection: str, space_id: str, owner: str
    ) -> None:
        """Lock the cursor node in `transaction` and check `owner` holds the live lease.

        Raises:
            IndexSyncInProgressError: The lease is not `owner`'s or has expired; the caller's
                transaction is left uncommitted.
        """
        held: list[dict[str, Any]] = await transaction.run(
            FENCE,
            {
                "cursor_key": cursor_key(projection, space_id),
                "owner": owner,
                "now": self._clock.now(),
            },
        )
        if not held:
            raise lease_lost(projection, space_id)


def cursor_key(projection: str, space_id: str) -> str:
    """The `cursor_key` of a projection in a space."""
    return f"{projection}:{space_id}"


def _identity(projection: str, space_id: str) -> dict[str, str]:
    return {
        "cursor_key": cursor_key(projection, space_id),
        "projection": projection,
        "space_id": space_id,
    }
