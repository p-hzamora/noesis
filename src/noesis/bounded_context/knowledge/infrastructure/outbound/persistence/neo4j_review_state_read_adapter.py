"""`IReviewStateReadRepository`: derived review states and pending supersession effects."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import PendingEffectDto, ReviewStateDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.domain.services.review_state import authority_of
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .mappers import decision_key
from .neo4j_review_record_support import RecordRow, fetch_record_rows

_LATEST_DECISIONS: LiteralString = """
UNWIND $keys AS key
MATCH (decision:Decision {decision_key: key})
RETURN decision.decision_key AS key, decision.actor_kind AS actor_kind,
       decision.decided_at AS decided_at
"""
_PENDING: LiteralString = """
MATCH (assertion:Assertion {space_id: $space_id, predicate: 'supersedes', status: 'accepted'})
      -[:OBJECT]->(target:Record {status: 'accepted'})
RETURN assertion.id AS assertion_id, target.id AS object_id
ORDER BY assertion.id
"""


class Neo4jReviewStateReadAdapter(IReviewStateReadRepository):
    """Each call reads in its own short transaction; `authority` comes from the domain."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get_states(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[ReviewStateDto]:
        """One state per id known in the space, in the order given."""
        if not ids:
            return []
        async with await self._client.begin() as transaction:
            rows: dict[str, RecordRow] = await fetch_record_rows(transaction, space_id, list(ids))
            keys: list[str] = [
                decision_key(RecordId(value=record_id), row.node["decision_seq"])
                for record_id, row in rows.items()
                if row.node.get("decision_seq", 0) > 0
            ]
            decisions: list[dict[str, Any]] = (
                await transaction.run(_LATEST_DECISIONS, {"keys": keys}) if keys else []
            )
        latest: dict[str, dict[str, Any]] = {row["key"]: row for row in decisions}
        return [
            self._state(row, latest.get(decision_key(item, row.node.get("decision_seq", 0))))
            for item in ids
            if (row := rows.get(item.value)) is not None
        ]

    async def list_pending_effects(self, space_id: SpaceId) -> list[PendingEffectDto]:
        """Accepted `supersedes` assertions whose object's stored status is still `accepted`."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _PENDING, {"space_id": space_id.value}
            )
        return [
            PendingEffectDto(assertion_id=r["assertion_id"], object_id=r["object_id"]) for r in rows
        ]

    @staticmethod
    def _state(row: RecordRow, decision: dict[str, Any] | None) -> ReviewStateDto:
        node = row.node
        effective = row.effective_status
        superseded_by: str | None = (
            row.superseders[0][0] if row.superseders else node.get("superseded_by_assertion_id")
        )
        return ReviewStateDto(
            record_id=node["id"],
            record_type=row.record_type.value,
            status=row.stored_status.value if row.stored_status else None,
            effective_status=effective.value if effective else None,
            authority=authority_of(effective).value,
            head_revision=node.get("head_revision"),
            superseded_by_assertion_id=superseded_by,
            superseded_by_record_ids=tuple(subject for _, subject in row.superseders),
            project_key=row.project_key,
            tags=tuple(node.get("tags", [])),
            decided_by_kind=decision["actor_kind"] if decision else None,
            decided_at=decision["decided_at"].isoformat() if decision else None,
        )
