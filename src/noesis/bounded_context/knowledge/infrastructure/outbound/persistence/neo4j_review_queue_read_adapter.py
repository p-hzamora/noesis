"""`IReviewQueueReadRepository`: the review queue and the tag selection of the bulk accept."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import (
    ReviewQueueItemDto,
    ReviewQueuePageDto,
    TaggedProposalDto,
    TagMatchCountsDto,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewQueueReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordTypeEnum,
    SpaceId,
    Tag,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

# Proposed Knowledge and Assertions. `$project_key` lists that project plus space-wide items,
# `$global_only` only the space-wide ones. The optional match on C9's reserved
# `(:Consolidation)-[:PRODUCED]->(:Record)` edge reads `consolidation_id`; it is null while no
# such edge exists and the absent label raises no notification worth a warning.
_QUEUE: LiteralString = """
MATCH (record:Record {space_id: $space_id, status: 'proposed'})
WHERE (record:Knowledge OR record:Assertion)
  AND ($record_type IS NULL OR $record_type = CASE WHEN record:Knowledge THEN 'knowledge' ELSE 'assertion' END)
  AND ($predicate IS NULL OR record.predicate = $predicate)
  AND ($cursor IS NULL OR record.id > $cursor)
OPTIONAL MATCH (record)-[:BELONGS_TO_PROJECT]->(project:Project)
WITH record, project
WHERE ($global_only AND project IS NULL)
   OR (NOT $global_only AND ($project_key IS NULL OR project IS NULL OR project.key = $project_key))
ORDER BY record.id
LIMIT $fetch
OPTIONAL MATCH (consolidation:Consolidation)-[:PRODUCED]->(record)
WITH record, project, head(collect(consolidation.id)) AS consolidation_id
OPTIONAL MATCH (head:Revision {revision_key: record.id + ':' + toString(record.head_revision)})
RETURN properties(record) AS node, labels(record) AS labels, project.key AS project_key,
       consolidation_id, head.title AS title
ORDER BY record.id
"""
_COUNT: LiteralString = """
MATCH (knowledge:Knowledge {space_id: $space_id})
WHERE $tag IN knowledge.tags
RETURN count(knowledge) AS matched,
       count(CASE WHEN knowledge.status = 'proposed' THEN 1 END) AS proposed
"""
_PROPOSED_BY_TAG: LiteralString = """
MATCH (knowledge:Knowledge {space_id: $space_id, status: 'proposed'})
WHERE $tag IN knowledge.tags AND ($after_id IS NULL OR knowledge.id > $after_id)
WITH knowledge
ORDER BY knowledge.id
LIMIT $limit
OPTIONAL MATCH (knowledge)-[:BELONGS_TO_PROJECT]->(project:Project)
MATCH (head:Revision {revision_key: knowledge.id + ':' + toString(knowledge.head_revision)})
RETURN knowledge.id AS id, head.title AS title, knowledge.subtype AS subtype,
       project.key AS project_key, knowledge.head_revision AS head_revision
ORDER BY knowledge.id
"""


class Neo4jReviewQueueReadAdapter(IReviewQueueReadRepository):
    """Each call reads in its own short transaction."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def list_queue(
        self,
        space_id: SpaceId,
        *,
        project: Key | None,
        global_only: bool,
        record_type: RecordTypeEnum | None,
        predicate: AssertionPredicateEnum | None,
        limit: int,
        cursor: str | None,
    ) -> ReviewQueuePageDto:
        """Proposed records, ascending id; the cursor is the last id of the previous page."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _QUEUE,
                {
                    "space_id": space_id.value,
                    "project_key": project.value if project else None,
                    "global_only": global_only,
                    "record_type": record_type.value if record_type else None,
                    "predicate": predicate.value if predicate else None,
                    "cursor": cursor,
                    "fetch": limit + 1,
                },
            )
        page: list[dict[str, Any]] = rows[:limit]
        return ReviewQueuePageDto(
            items=tuple(self._item(row) for row in page),
            next_cursor=page[-1]["node"]["id"] if len(rows) > limit else None,
        )

    async def count_by_tag(self, space_id: SpaceId, tag: Tag) -> TagMatchCountsDto:
        """Knowledge carrying `tag` (any status) and how many of them are stored `proposed`."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _COUNT, {"space_id": space_id.value, "tag": tag.value}
            )
        return TagMatchCountsDto(matched=rows[0]["matched"], proposed=rows[0]["proposed"])

    async def list_proposed_by_tag(
        self, space_id: SpaceId, tag: Tag, *, after_id: RecordId | None, limit: int
    ) -> list[TaggedProposalDto]:
        """Proposed Knowledge carrying `tag`, ascending id, with ids greater than `after_id`."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _PROPOSED_BY_TAG,
                {
                    "space_id": space_id.value,
                    "tag": tag.value,
                    "after_id": after_id.value if after_id else None,
                    "limit": limit,
                },
            )
        return [TaggedProposalDto(**row) for row in rows]

    @staticmethod
    def _item(row: dict[str, Any]) -> ReviewQueueItemDto:
        node: dict[str, Any] = row["node"]
        is_knowledge: bool = "Knowledge" in row["labels"]
        return ReviewQueueItemDto(
            id=node["id"],
            type="knowledge" if is_knowledge else "assertion",
            title=row["title"] if is_knowledge else None,
            predicate=None if is_knowledge else node["predicate"],
            subject_id=None if is_knowledge else node["subject_id"],
            object_id=None if is_knowledge else node["object_id"],
            project_id=node.get("project_id"),
            project_key=row["project_key"],
            tags=tuple(node.get("tags", [])),
            evidence_count=None if is_knowledge else len(node.get("evidence_ids", [])),
            consolidation_id=row["consolidation_id"],
        )
