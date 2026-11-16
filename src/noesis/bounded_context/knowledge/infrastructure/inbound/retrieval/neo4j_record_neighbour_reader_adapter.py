"""Graph neighbours (structural `IRecordNeighbourReader`): records sharing a Source with a seed.

A Knowledge record cites Sources through its head revision's `FROM_SOURCE` edges; an Experience
through its own. Project membership is not traversed.
"""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.shared_kernel.contracts.knowledge import GraphNeighbourContract
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

# `holder` is what carries the FROM_SOURCE edges: the head revision (Knowledge) or the Experience.
# The cap bounds distinct neighbour records, best first (the sum over seeds of the Sources shared
# with each seed, then record id); every (neighbour, seed) pair of a kept record is returned.
_NEIGHBOURS: LiteralString = """
MATCH (seed:Record {space_id: $space_id})
WHERE (seed:Knowledge OR seed:Experience) AND seed.id IN $seed_ids
OPTIONAL MATCH (seed_head:Revision {revision_key: seed.id + ':' + toString(seed.head_revision)})
WITH seed, coalesce(seed_head, seed) AS seed_holder
MATCH (seed_holder)-[:FROM_SOURCE]->(source:Source {space_id: $space_id})
MATCH (holder)-[:FROM_SOURCE]->(source)
WHERE holder <> seed_holder
OPTIONAL MATCH (holder)-[:REVISION_OF]->(knowledge:Knowledge {space_id: $space_id})
WITH seed, source, holder, knowledge
WHERE (knowledge IS NOT NULL AND holder.number = knowledge.head_revision)
   OR (holder:Experience AND holder.space_id = $space_id)
WITH seed, source, CASE WHEN knowledge IS NULL THEN holder ELSE knowledge END AS neighbour
WHERE NOT neighbour.id IN $seed_ids
WITH neighbour, seed, collect(DISTINCT source.id) AS shared
WITH neighbour, collect({seed_id: seed.id, shared: shared}) AS pairs
WITH neighbour, pairs, reduce(total = 0, pair IN pairs | total + size(pair.shared)) AS total
ORDER BY total DESC, neighbour.id
LIMIT $limit
UNWIND pairs AS pair
RETURN neighbour.id AS record_id, pair.seed_id AS seed_id, size(pair.shared) AS shared_sources
ORDER BY total DESC, record_id, seed_id
"""


class Neo4jRecordNeighbourReaderAdapter:
    """One `GraphNeighbourContract` per (neighbour, seed) pair, same space only."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def neighbours(
        self, seed_ids: Sequence[str], *, space_id: str, limit: int
    ) -> list[GraphNeighbourContract]:
        """Neighbours of `seed_ids`; `limit` bounds the distinct neighbour records.

        Ordering and the final cap of the graph candidate list are Retrieval's job; here the
        records kept are those with the highest per-seed shared-Source sum.
        """
        if not seed_ids:
            return []
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _NEIGHBOURS, {"seed_ids": [*seed_ids], "space_id": space_id, "limit": limit}
            )
        return [
            GraphNeighbourContract(
                record_id=row["record_id"],
                seed_id=row["seed_id"],
                shared_sources=row["shared_sources"],
            )
            for row in rows
        ]
