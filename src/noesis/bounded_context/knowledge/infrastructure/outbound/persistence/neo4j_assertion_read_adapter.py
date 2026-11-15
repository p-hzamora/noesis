"""`IAssertionReadRepository`: assertions as DTOs, with the effective status of their ends."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import AssertionDto, AssertionSummaryDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IAssertionReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    AssertionRoleEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers import record_type_of
from .neo4j_review_record_support import RecordRow, fetch_record_rows

_TAIL: LiteralString = """
MATCH (assertion)-[subject_edge:SUBJECT]->(:Record)
MATCH (assertion)-[object_edge:OBJECT]->(target:Record)
OPTIONAL MATCH (assertion)-[:BELONGS_TO_PROJECT]->(project:Project)
RETURN properties(assertion) AS node, project.key AS project_key,
       subject_edge.at_revision AS subject_at_revision,
       object_edge.at_revision AS object_at_revision, labels(target) AS object_labels
ORDER BY assertion.id
"""
_ABOUT: LiteralString = (
    """
MATCH (assertion:Assertion {space_id: $space_id})
WHERE ((($role = 'subject' OR $role = 'any') AND assertion.subject_id = $id)
    OR (($role = 'object' OR $role = 'any') AND assertion.object_id = $id)
    OR (($role = 'evidence' OR $role = 'any') AND $id IN assertion.evidence_ids))
  AND (size($statuses) = 0 OR assertion.status IN $statuses)
  AND (size($predicates) = 0 OR assertion.predicate IN $predicates)
"""
    + _TAIL
)
_BY_ID: LiteralString = (
    """
MATCH (assertion:Assertion {id: $id, space_id: $space_id})
"""
    + _TAIL
)
_BY_SUBJECTS: LiteralString = (
    """
MATCH (assertion:Assertion {space_id: $space_id})
WHERE assertion.subject_id IN $subject_ids
  AND (size($statuses) = 0 OR assertion.status IN $statuses)
  AND (size($predicates) = 0 OR assertion.predicate IN $predicates)
"""
    + _TAIL
)


class Neo4jAssertionReadAdapter(IAssertionReadRepository):
    """Each call reads in its own short transaction."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> AssertionDto | None:
        """The assertion, or None (also when it is in another space)."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _BY_ID, {"id": record_id.value, "space_id": space_id.value}
            )
            found: list[AssertionDto] = await self._dtos(transaction, space_id, rows)
        return found[0] if found else None

    async def list_about(
        self,
        record_id: RecordId,
        *,
        space_id: SpaceId,
        role: AssertionRoleEnum,
        statuses: Sequence[RecordStatusEnum],
        predicates: Sequence[AssertionPredicateEnum],
    ) -> list[AssertionDto]:
        """Assertions in which the record plays `role`; empty filters match all."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _ABOUT,
                {
                    "id": record_id.value,
                    "space_id": space_id.value,
                    "role": role.value,
                    "statuses": [item.value for item in statuses],
                    "predicates": [item.value for item in predicates],
                },
            )
            return await self._dtos(transaction, space_id, rows)

    async def list_by_subjects(
        self,
        subject_ids: Sequence[RecordId],
        *,
        space_id: SpaceId,
        predicates: Sequence[AssertionPredicateEnum],
        statuses: Sequence[RecordStatusEnum],
    ) -> list[AssertionSummaryDto]:
        """Summaries of the assertions whose subject is in `subject_ids`, ascending id."""
        if not subject_ids:
            return []
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _BY_SUBJECTS,
                {
                    "space_id": space_id.value,
                    "subject_ids": [item.value for item in subject_ids],
                    "statuses": [item.value for item in statuses],
                    "predicates": [item.value for item in predicates],
                },
            )
        return [self._summary(row) for row in rows]

    @staticmethod
    def _summary(row: dict[str, Any]) -> AssertionSummaryDto:
        node: dict[str, Any] = row["node"]
        object_type = record_type_of(row["object_labels"])
        return AssertionSummaryDto(
            assertion_id=node["id"],
            predicate=node["predicate"],
            subject_id=node["subject_id"],
            subject_at_revision=row["subject_at_revision"],
            object_id=node["object_id"],
            object_at_revision=row["object_at_revision"],
            object_type=object_type.value if object_type else "",
            status=node["status"],
            evidence_ids=tuple(node.get("evidence_ids", [])),
            project_key=row["project_key"],
            tags=tuple(node.get("tags", [])),
        )

    @staticmethod
    async def _dtos(
        transaction: Neo4jTransaction, space_id: SpaceId, rows: list[dict[str, Any]]
    ) -> list[AssertionDto]:
        ids: list[RecordId] = [
            RecordId(value=value)
            for row in rows
            for value in (row["node"]["id"], row["node"]["subject_id"], row["node"]["object_id"])
        ]
        records: dict[str, RecordRow] = await fetch_record_rows(
            transaction, space_id, list(dict.fromkeys(ids))
        )
        dtos: list[AssertionDto] = []
        for row in rows:
            node: dict[str, Any] = row["node"]
            own: RecordRow = records[node["id"]]
            subject: RecordRow | None = records.get(node["subject_id"])
            target: RecordRow | None = records.get(node["object_id"])
            subject_status = subject.effective_status if subject else None
            object_status = target.effective_status if target else None
            effective = own.effective_status
            dtos.append(
                AssertionDto(
                    id=node["id"],
                    space_id=node["space_id"],
                    predicate=node["predicate"],
                    subject_id=node["subject_id"],
                    subject_at_revision=row["subject_at_revision"],
                    subject_effective_status=subject_status.value if subject_status else None,
                    object_id=node["object_id"],
                    object_at_revision=row["object_at_revision"],
                    object_effective_status=object_status.value if object_status else None,
                    evidence_ids=tuple(node.get("evidence_ids", [])),
                    rationale=node["rationale"],
                    project_key=row["project_key"],
                    tags=tuple(node.get("tags", [])),
                    status=node["status"],
                    effective_status=effective.value if effective else node["status"],
                    superseded_by_assertion_id=own.superseders[0][0] if own.superseders else None,
                    superseded_by_record_id=own.superseders[0][1] if own.superseders else None,
                    actor_kind=node["actor_kind"],
                    actor_name=node["actor_name"],
                    actor_session=node.get("actor_session"),
                    source_ids=tuple(node.get("source_ids", [])),
                    created_at=node["created_at"].isoformat(),
                )
            )
        return dtos
