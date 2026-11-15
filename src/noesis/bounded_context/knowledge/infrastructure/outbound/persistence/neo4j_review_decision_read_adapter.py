"""`IReviewDecisionReadRepository` over `:Decision` nodes."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import ReviewDecisionDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewDecisionReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .mappers import DecisionNodeMapper

_DECISIONS: LiteralString = """
MATCH (decision:Decision)-[:DECIDES]->(:Record {id: $id, space_id: $space_id})
RETURN properties(decision) AS decision
ORDER BY decision.seq
"""


class Neo4jReviewDecisionReadAdapter(IReviewDecisionReadRepository):
    """Each call reads in its own short transaction."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def list_for(self, record_id: RecordId, *, space_id: SpaceId) -> list[ReviewDecisionDto]:
        """Decisions of the record ordered by `seq`; empty when none or unknown."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _DECISIONS, {"id": record_id.value, "space_id": space_id.value}
            )
        return [DecisionNodeMapper.to_dto(row["decision"]) for row in rows]
