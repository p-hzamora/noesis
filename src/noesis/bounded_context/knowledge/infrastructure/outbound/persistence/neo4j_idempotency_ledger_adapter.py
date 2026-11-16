"""`IIdempotencyLedger` over `:IdempotencyKey` nodes, unique by `<space_id>:<key>`."""

import json
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.ports.ledger import (
    IIdempotencyLedger,
    LedgerEntry,
)
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.exceptions import RevisionConflictError
from noesis.shared_kernel.domain import JsonValue

from .mappers import LedgerEntryNodeMapper, ledger_key
from .neo4j_write_support import TransactionProvider, create_unique

_CREATE: LiteralString = "CREATE (entry:IdempotencyKey $entry)"
_LOCK: LiteralString = """
MATCH (entry:IdempotencyKey {key: $key})
SET entry._lock = true
REMOVE entry._lock
RETURN entry.extra AS extra
"""
_UPDATE: LiteralString = "MATCH (entry:IdempotencyKey {key: $key}) SET entry.extra = $extra"
PROGRESS_VERSION: str = "progress_version"
_GET: LiteralString = "MATCH (entry:IdempotencyKey {key: $key}) RETURN properties(entry) AS entry"


class Neo4jIdempotencyLedgerAdapter(IIdempotencyLedger):
    """Ledger entries commit in the same transaction as the change they describe (A-8).

    Keys are kept indefinitely (D-026). Racing first attempts collide on the
    `IdempotencyKey.key` constraint: the loser waits for the winner's commit, then fails.
    """

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def get(self, space_id: SpaceId, key: str) -> LedgerEntry | None:
        """The entry for (space, key), or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _GET, {"key": ledger_key(space_id, key)}
        )
        return LedgerEntryNodeMapper.to_entry(rows[0]["entry"]) if rows else None

    async def record(self, entry: LedgerEntry) -> None:
        """Stage `entry`.

        Raises:
            EntryAlreadyExistsError: (space, key) is already recorded.
        """
        await create_unique(
            self._transaction(),
            _CREATE,
            {"entry": LedgerEntryNodeMapper.to_properties(entry)},
            what="idempotency key",
            key=entry.key,
        )

    async def update_extra(
        self,
        space_id: SpaceId,
        key: str,
        *,
        expected_progress_version: int,
        extra: dict[str, JsonValue],
    ) -> None:
        """Replace `extra` of a pending entry by compare-and-set on `progress_version`.

        The entry's lock is taken first, so a concurrent update waits and then fails its check.

        Raises:
            RevisionConflictError: The entry is unknown or its progress version moved on.
        """
        transaction = self._transaction()
        rows: list[dict[str, Any]] = await transaction.run(
            _LOCK, {"key": ledger_key(space_id, key)}
        )
        stored: Any = json.loads(rows[0]["extra"]) if rows else None
        actual: Any = stored.get(PROGRESS_VERSION) if isinstance(stored, dict) else None
        if actual != expected_progress_version:
            raise RevisionConflictError(
                f"Expected progress version {expected_progress_version} but it is {actual}.",
                {
                    "key": key,
                    "expected_progress_version": expected_progress_version,
                    "actual_progress_version": actual,
                },
                next_steps=["Run the command again; another run of it moved the progress on."],
            )
        updated: dict[str, JsonValue] = {**extra, PROGRESS_VERSION: expected_progress_version + 1}
        await transaction.run(
            _UPDATE,
            {
                "key": ledger_key(space_id, key),
                "extra": json.dumps(updated, sort_keys=True, separators=(",", ":")),
            },
        )
