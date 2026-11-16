"""`IConsolidationReadRepository`: consolidations and candidate snapshots as DTOs."""

import base64
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import (
    CandidateSnapshotDto,
    CandidateSnapshotPageDto,
    ConsolidationDto,
    ConsolidationPageDto,
    OpenMembershipDto,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    MIGRATED_TAG,
    ConsolidationId,
    ConsolidationStateEnum,
    DismissedPair,
    Key,
    RecordId,
    SpaceId,
)
from noesis.exceptions import InvalidConsolidationError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .mappers.consolidation_node_mapper import ConsolidationNodeMapper
from .neo4j_consolidation_support import dismissed_pairs, open_memberships
from .neo4j_review_record_support import RecordRow, fetch_record_rows

_GET: LiteralString = """
MATCH (consolidation:Consolidation {id: $id, space_id: $space_id})
OPTIONAL MATCH (project:Project {id: consolidation.project_id, space_id: $space_id})
OPTIONAL MATCH (membership:ConsolidationMembership)-[:OF]->(consolidation)
RETURN properties(consolidation) AS node, project.key AS project_key,
       collect(properties(membership)) AS members
"""
_LIST: LiteralString = """
MATCH (consolidation:Consolidation {space_id: $space_id})
WHERE ($state IS NULL OR consolidation.state = $state)
  AND ($cursor IS NULL OR consolidation.id > $cursor)
OPTIONAL MATCH (project:Project {id: consolidation.project_id, space_id: $space_id})
WITH consolidation, project
WHERE ($project_key IS NULL AND consolidation.project_id IS NULL) OR project.key = $project_key
ORDER BY consolidation.id
LIMIT $fetch
OPTIONAL MATCH (membership:ConsolidationMembership)-[:OF]->(consolidation)
RETURN properties(consolidation) AS node, project.key AS project_key,
       collect(properties(membership)) AS members
ORDER BY node.id
"""
_DETAILS: LiteralString = """
MATCH (record:Knowledge {space_id: $space_id})
WHERE record.id IN $ids
OPTIONAL MATCH (head:Revision {revision_key: record.id + ':' + toString(record.head_revision)})
OPTIONAL MATCH (decision:Decision {transition: 'accept'})-[:DECIDES]->(record)
RETURN record.id AS id, head.title AS title, max(decision.decided_at) AS accepted_at
"""
# Accepted Knowledge that no accepted `supersedes` targets, in the scope of `$project_key`
# (space-wide when null), latest accept first; null accept times sort last.
_RECENT: LiteralString = """
MATCH (record:Knowledge {space_id: $space_id, status: 'accepted'})
WHERE NOT EXISTS { MATCH (:Assertion {predicate: 'supersedes', status: 'accepted'})-[:OBJECT]->(record) }
OPTIONAL MATCH (project:Project {id: record.project_id, space_id: $space_id})
WITH record, project
WHERE ($project_key IS NULL AND record.project_id IS NULL) OR project.key = $project_key
OPTIONAL MATCH (decision:Decision {transition: 'accept'})-[:DECIDES]->(record)
WITH record, coalesce(max(decision.decided_at), datetime({epochMillis: 0})) AS accepted_at
WHERE $cursor_at IS NULL OR accepted_at < $cursor_at
   OR (accepted_at = $cursor_at AND record.id > $cursor_id)
RETURN record.id AS id, accepted_at
ORDER BY accepted_at DESC, id ASC
LIMIT $fetch
"""
_MIGRATED: LiteralString = """
MATCH (record:Knowledge {space_id: $space_id, status: 'proposed'})
WHERE $tag IN record.tags
OPTIONAL MATCH (project:Project {id: record.project_id, space_id: $space_id})
WITH record, project
WHERE ($project_key IS NULL AND record.project_id IS NULL) OR project.key = $project_key
RETURN count(record) AS total
"""


def _scope(project: Key | None) -> str:
    return f"project:{project.value}" if project is not None else "global"


def _encode_cursor(scope: str, accepted_at: datetime, record_id: str) -> str:
    raw: str = json.dumps({"scope": scope, "at": accepted_at.isoformat(), "id": record_id})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str, scope: str) -> tuple[datetime, str]:
    try:
        data: dict[str, str] = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        moment: datetime = datetime.fromisoformat(data["at"])
        if data["scope"] != scope:
            raise KeyError("scope")
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC), data["id"]
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidConsolidationError(
            "The cursor does not belong to this scan.",
            {"cursor": cursor},
            next_steps=["Start again without --cursor."],
        ) from error


class Neo4jConsolidationReadAdapter(IConsolidationReadRepository):
    """Each call reads in its own short transaction, scoped to one space."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get(
        self, consolidation_id: ConsolidationId, space_id: SpaceId
    ) -> ConsolidationDto | None:
        """The consolidation, or None; another space's reads as None."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _GET, {"id": consolidation_id.value, "space_id": space_id.value}
            )
        if not rows or rows[0]["node"] is None:
            return None
        row: dict[str, Any] = rows[0]
        return ConsolidationNodeMapper.to_dto(row["node"], row["members"], row["project_key"])

    async def list_consolidations(
        self,
        space_id: SpaceId,
        *,
        project: Key | None,
        state: ConsolidationStateEnum | None,
        limit: int,
        cursor: str | None,
    ) -> ConsolidationPageDto:
        """Consolidations of `project`, or of the space-wide records when None, ascending id."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _LIST,
                {
                    "space_id": space_id.value,
                    "project_key": project.value if project else None,
                    "state": state.value if state else None,
                    "cursor": cursor,
                    "fetch": limit + 1,
                },
            )
        items: list[ConsolidationDto] = [
            ConsolidationNodeMapper.to_dto(row["node"], row["members"], row["project_key"])
            for row in rows
        ]
        page: list[ConsolidationDto] = items[:limit]
        return ConsolidationPageDto(
            items=tuple(page), next_cursor=page[-1].id if len(items) > limit else None
        )

    async def describe(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[CandidateSnapshotDto]:
        """One snapshot per id that is a record of the space, in the order given."""
        ids: list[RecordId] = list(dict.fromkeys(record_ids))
        async with await self._client.begin() as transaction:
            records: dict[str, RecordRow] = await fetch_record_rows(transaction, space_id, ids)
            details: list[dict[str, Any]] = await transaction.run(
                _DETAILS, {"space_id": space_id.value, "ids": [item.value for item in ids]}
            )
        extra: dict[str, dict[str, Any]] = {row["id"]: row for row in details}
        snapshots: list[CandidateSnapshotDto] = []
        for record_id in ids:
            record: RecordRow | None = records.get(record_id.value)
            if record is None:
                continue
            more: dict[str, Any] = extra.get(record_id.value, {})
            accepted_at: datetime | None = more.get("accepted_at")
            effective = record.effective_status
            snapshots.append(
                CandidateSnapshotDto(
                    record_id=record_id.value,
                    record_type=record.record_type.value,
                    subtype=record.node.get("subtype"),
                    project_id=record.node.get("project_id"),
                    project_key=record.project_key,
                    tags=tuple(record.node.get("tags", [])),
                    stored_status=record.node.get("status"),
                    effective_status=effective.value if effective else None,
                    head_revision=record.node.get("head_revision"),
                    title=more.get("title"),
                    accepted_at=accepted_at.isoformat() if accepted_at else None,
                )
            )
        return snapshots

    async def recent_accepted(
        self, space_id: SpaceId, *, project: Key | None, limit: int, cursor: str | None
    ) -> CandidateSnapshotPageDto:
        """Accepted, not superseded Knowledge of `project` (space-wide when None)."""
        scope: str = _scope(project)
        cursor_at: datetime | None = None
        cursor_id: str | None = None
        if cursor is not None:
            cursor_at, cursor_id = _decode_cursor(cursor, scope)
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _RECENT,
                {
                    "space_id": space_id.value,
                    "project_key": project.value if project else None,
                    "cursor_at": cursor_at,
                    "cursor_id": cursor_id,
                    "fetch": limit + 1,
                },
            )
        page: list[dict[str, Any]] = rows[:limit]
        items: list[CandidateSnapshotDto] = await self.describe(
            [RecordId(value=row["id"]) for row in page], space_id
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last: dict[str, Any] = page[-1]
            next_cursor = _encode_cursor(scope, last["accepted_at"], last["id"])
        return CandidateSnapshotPageDto(items=tuple(items), next_cursor=next_cursor)

    async def count_unaccepted_migrated(self, space_id: SpaceId, *, project: Key | None) -> int:
        """Proposed Knowledge tagged `origin:migrated` in that scope."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _MIGRATED,
                {
                    "space_id": space_id.value,
                    "project_key": project.value if project else None,
                    "tag": MIGRATED_TAG,
                },
            )
        return int(rows[0]["total"])

    async def conflicts(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[OpenMembershipDto]:
        """The records among `record_ids` that an open consolidation holds."""
        async with await self._client.begin() as transaction:
            return await open_memberships(transaction, record_ids, space_id)

    async def dismissed_pairs(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[DismissedPair]:
        """`distinct` dismissals that judged two of `record_ids`."""
        async with await self._client.begin() as transaction:
            return await dismissed_pairs(transaction, record_ids, space_id)
