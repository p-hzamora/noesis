"""Record state reader (structural `IRecordStateReader`): head revision, status, scope, times."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.shared_kernel.contracts.knowledge import RecordStateContract
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .record_node_contracts import NodeProperties, ownership_of, record_type_of

_STATES: LiteralString = """
MATCH (record:Record {space_id: $space_id})
WHERE (record:Knowledge OR record:Experience)
  AND record.id IN $ids
OPTIONAL MATCH (head:Revision {revision_key: record.id + ':' + toString(record.head_revision)})
RETURN properties(record) AS record, labels(record) AS labels, properties(head) AS head
ORDER BY record.id
"""
_SCAN: LiteralString = """
MATCH (record:Record {space_id: $space_id})
WHERE (record:Knowledge OR record:Experience)
  AND ($after_id IS NULL OR record.id > $after_id)
WITH record ORDER BY record.id LIMIT $limit
OPTIONAL MATCH (head:Revision {revision_key: record.id + ':' + toString(record.head_revision)})
RETURN properties(record) AS record, labels(record) AS labels, properties(head) AS head
ORDER BY record.id
"""
_PROJECT: LiteralString = """
MATCH (project:Project {project_key: $project_key})
RETURN project.id AS id
"""


class Neo4jRecordStateReaderAdapter:
    """Reads states of Knowledge and Experience records, always inside one space."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get_states(
        self, record_ids: Sequence[str], *, space_id: str
    ) -> list[RecordStateContract]:
        """States of the given ids; ids not found in the space are omitted."""
        if not record_ids:
            return []
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _STATES, {"space_id": space_id, "ids": [*record_ids]}
            )
        return _contracts(rows)

    async def scan_states(
        self, space_id: str, *, after_id: str | None, limit: int
    ) -> list[RecordStateContract]:
        """Up to `limit` states ordered by record id, starting after `after_id`."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _SCAN, {"space_id": space_id, "after_id": after_id, "limit": limit}
            )
        return _contracts(rows)

    async def find_project_id(self, project_key: str, *, space_id: str) -> str | None:
        """The id of the project with this key in the space, or None."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _PROJECT, {"project_key": f"{space_id}:{project_key}"}
            )
        return str(rows[0]["id"]) if rows else None


def _contracts(rows: list[dict[str, Any]]) -> list[RecordStateContract]:
    contracts: list[RecordStateContract] = []
    for row in rows:
        record: NodeProperties = row["record"]
        head: NodeProperties | None = row["head"]
        record_type: str | None = record_type_of(row["labels"])
        if record_type is None:
            continue
        revised_at = head["created_at"] if head is not None else record["created_at"]
        contracts.append(
            RecordStateContract(
                record_id=record["id"],
                record_type=record_type,
                subtype=record.get("subtype"),
                ownership=ownership_of(record_type, record),
                head_revision=record.get("head_revision"),
                status=record.get("status"),
                project_id=record.get("project_id"),
                tags=tuple(sorted(record.get("tags", []))),
                title=head.get("title") if head is not None else None,
                revised_at=revised_at,
            )
        )
    return contracts
