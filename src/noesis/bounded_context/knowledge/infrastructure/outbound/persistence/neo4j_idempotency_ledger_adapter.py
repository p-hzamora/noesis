"""`IIdempotencyLedger` over `:IdempotencyKey` nodes, unique by `<space_id>:<key>`."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.ports.ledger import (
    IIdempotencyLedger,
    LedgerEntry,
)
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId

from .mappers import LedgerEntryNodeMapper, ledger_key
from .neo4j_write_support import TransactionProvider, create_unique

_CREATE: LiteralString = "CREATE (entry:IdempotencyKey $entry)"
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
