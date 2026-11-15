"""`IRecordReadRepository` over the record nodes: DTOs, scoped to one space."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import RecordDto, RevisionDto, SourceDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Key,
    RecordId,
    RecordTypeEnum,
    SpaceId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers import RecordDtoMapper, ReviewView, record_type_of, revision_key
from .neo4j_review_record_support import RecordRow, fetch_record_rows

_SPACE_ID: LiteralString = "MATCH (space:Space {key: $key}) RETURN space.id AS id"
_RECORD: LiteralString = """
MATCH (record:Record {id: $id, space_id: $space_id})
RETURN properties(record) AS record, labels(record) AS labels
"""
_REVISION: LiteralString = """
MATCH (revision:Revision {revision_key: $revision_key})
      -[:REVISION_OF]->(:Knowledge {id: $id, space_id: $space_id})
RETURN properties(revision) AS revision
"""
_ENDPOINT_REVISIONS: LiteralString = """
MATCH (:Assertion {id: $id, space_id: $space_id})-[subject:SUBJECT]->(:Record)
MATCH (:Assertion {id: $id, space_id: $space_id})-[object:OBJECT]->(:Record)
RETURN subject.at_revision AS subject_at_revision, object.at_revision AS object_at_revision
"""
_SOURCES: LiteralString = """
MATCH (source:Source {space_id: $space_id})
WHERE source.id IN $ids
RETURN properties(source) AS source
"""


class Neo4jRecordReadRepositoryAdapter(IRecordReadRepository):
    """Each call reads in its own short transaction; another space's record reads as None."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get_space_id(self, key: Key) -> SpaceId | None:
        """Id of the space with this key, or None."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_SPACE_ID, {"key": key.value})
        return SpaceId(value=rows[0]["id"]) if rows else None

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> RecordDto | None:
        """The record with its head revision (knowledge) or its sources (experience), or None."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _RECORD, {"id": record_id.value, "space_id": space_id.value}
            )
            if not rows:
                return None
            node: dict[str, Any] = rows[0]["record"]
            record_type: RecordTypeEnum | None = record_type_of(rows[0]["labels"])
            if record_type is None:
                return None
            revision: RevisionDto | None = None
            sources: tuple[SourceDto, ...] = ()
            if record_type is RecordTypeEnum.KNOWLEDGE:
                revision = await self._revision(
                    transaction, record_id, node["head_revision"], space_id
                )
                sources = revision.sources if revision else ()
            elif record_type in (RecordTypeEnum.EXPERIENCE, RecordTypeEnum.ASSERTION):
                sources = await self._sources(transaction, node["source_ids"], space_id)
            review: ReviewView | None = await self._review(
                transaction, record_id, record_type, space_id
            )
        return RecordDtoMapper.to_record_dto(
            node, record_type, revision=revision, sources=sources, review=review
        )

    @staticmethod
    async def _review(
        transaction: Neo4jTransaction,
        record_id: RecordId,
        record_type: RecordTypeEnum,
        space_id: SpaceId,
    ) -> ReviewView | None:
        """Effective status and supersession (and the revisions judged, for an assertion)."""
        if record_type not in (RecordTypeEnum.KNOWLEDGE, RecordTypeEnum.ASSERTION):
            return None
        row: RecordRow = (await fetch_record_rows(transaction, space_id, [record_id]))[
            record_id.value
        ]
        effective = row.effective_status
        subject_at: int | None = None
        object_at: int | None = None
        if record_type is RecordTypeEnum.ASSERTION:
            ends: list[dict[str, Any]] = await transaction.run(
                _ENDPOINT_REVISIONS, {"id": record_id.value, "space_id": space_id.value}
            )
            subject_at, object_at = ends[0]["subject_at_revision"], ends[0]["object_at_revision"]
        return ReviewView(
            effective_status=effective.value if effective else None,
            superseded_by=row.superseders[0] if row.superseders else None,
            subject_at_revision=subject_at,
            object_at_revision=object_at,
        )

    async def get_revision(
        self, record_id: RecordId, number: int, *, space_id: SpaceId
    ) -> RevisionDto | None:
        """Revision `number` of a Knowledge record in `space_id`, or None."""
        async with await self._client.begin() as transaction:
            return await self._revision(transaction, record_id, number, space_id)

    async def _revision(
        self, transaction: Neo4jTransaction, record_id: RecordId, number: int, space_id: SpaceId
    ) -> RevisionDto | None:
        rows: list[dict[str, Any]] = await transaction.run(
            _REVISION,
            {
                "revision_key": revision_key(record_id, number),
                "id": record_id.value,
                "space_id": space_id.value,
            },
        )
        if not rows:
            return None
        node: dict[str, Any] = rows[0]["revision"]
        sources: tuple[SourceDto, ...] = await self._sources(
            transaction, node["source_ids"], space_id
        )
        return RecordDtoMapper.to_revision_dto(node, sources)

    @staticmethod
    async def _sources(
        transaction: Neo4jTransaction, ids: Sequence[str], space_id: SpaceId
    ) -> tuple[SourceDto, ...]:
        """The cited sources in citation order."""
        rows: list[dict[str, Any]] = await transaction.run(
            _SOURCES, {"ids": list(ids), "space_id": space_id.value}
        )
        found: dict[str, SourceDto] = {
            row["source"]["id"]: RecordDtoMapper.to_source_dto(row["source"]) for row in rows
        }
        return tuple(found[source_id] for source_id in ids if source_id in found)
