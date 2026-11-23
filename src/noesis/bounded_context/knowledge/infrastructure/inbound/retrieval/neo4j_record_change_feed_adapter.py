"""Change feed reader over `:Change` and `:ChangeCounter` nodes (`IRecordChangeFeed`)."""

from typing import Any, LiteralString

from noesis.shared_kernel.contracts.knowledge import RecordChangedContract
from noesis.shared_kernel.contracts.ports.retrieval import IRecordChangeFeed
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

_AFTER: LiteralString = """
MATCH (change:Change {space_id: $space_id})
WHERE change.sequence > $sequence
RETURN properties(change) AS change
ORDER BY change.sequence
LIMIT $limit
"""
_HEAD: LiteralString = """
OPTIONAL MATCH (counter:ChangeCounter {space_id: $space_id})
RETURN coalesce(counter.value, 0) AS head
"""


class Neo4jRecordChangeFeedAdapter(IRecordChangeFeed):
    """Reads the feed of one space in its own read transaction."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def changes_after(
        self, sequence: int, *, space_id: str, limit: int
    ) -> list[RecordChangedContract]:
        """Up to `limit` changes with a sequence above `sequence`, ascending."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _AFTER, {"space_id": space_id, "sequence": sequence, "limit": limit}
            )
        return [_to_contract(row["change"]) for row in rows]

    async def head_sequence(self, space_id: str) -> int:
        """The space's change counter; 0 when no change was ever appended."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_HEAD, {"space_id": space_id})
        return int(rows[0]["head"])


def _to_contract(node: dict[str, Any]) -> RecordChangedContract:
    return RecordChangedContract(
        event_id=node["event_id"],
        occurred_at=node["occurred_at"],
        sequence=node["sequence"],
        space_id=node["space_id"],
        record_id=node["record_id"],
        record_type=node["record_type"],
        change_kind=node["change_kind"],
        revision=node.get("revision"),
        status=node.get("status"),
    )
