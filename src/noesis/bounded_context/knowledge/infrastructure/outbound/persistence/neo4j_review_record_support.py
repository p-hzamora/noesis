"""Records of any type with their derived review state: one read the review adapters share.

A record's effective status is `superseded` when an accepted `supersedes` assertion has it as
object, whatever the stored status says (20-review.md, Derived states).
"""

from dataclasses import dataclass
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.services.review_state import effective_status_of
from noesis.bounded_context.knowledge.domain.value_objects import (
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
    SpaceId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jTransaction

from .mappers import NodeProperties, record_type_of

_RECORDS: LiteralString = """
MATCH (record:Record {space_id: $space_id})
WHERE record.id IN $ids
OPTIONAL MATCH (record)-[:BELONGS_TO_PROJECT]->(project:Project)
OPTIONAL MATCH (superseder:Assertion {predicate: 'supersedes', status: 'accepted'})
               -[:OBJECT]->(record)
WITH record, project,
     collect(CASE WHEN superseder IS NULL THEN null
                  ELSE {assertion_id: superseder.id, subject_id: superseder.subject_id} END)
         AS superseders
RETURN properties(record) AS node, labels(record) AS labels, project.key AS project_key,
       superseders
"""


@dataclass(frozen=True, slots=True)
class RecordRow:
    """One record node with what the review reads derive from its neighbourhood.

    Attributes:
        node: Node properties.
        record_type: Type from the node's labels.
        project_key: Key of the applicability project, or None.
        superseders: `(assertion_id, subject_id)` of the accepted `supersedes` assertions that
            target the record, ascending assertion id.
    """

    node: NodeProperties
    record_type: RecordTypeEnum
    project_key: str | None
    superseders: tuple[tuple[str, str], ...]

    @property
    def stored_status(self) -> RecordStatusEnum | None:
        """The stored status; None for types without status."""
        status: str | None = self.node.get("status")
        return RecordStatusEnum(status) if status is not None else None

    @property
    def effective_status(self) -> RecordStatusEnum | None:
        """The status a reader should see."""
        return effective_status_of(
            self.stored_status, superseded_by_accepted=bool(self.superseders)
        )


async def fetch_record_rows(
    transaction: Neo4jTransaction, space_id: SpaceId, ids: list[RecordId]
) -> dict[str, RecordRow]:
    """The known records among `ids` in `space_id`, keyed by id (unknown ids are absent)."""
    rows: list[dict[str, Any]] = await transaction.run(
        _RECORDS, {"space_id": space_id.value, "ids": [item.value for item in ids]}
    )
    found: dict[str, RecordRow] = {}
    for row in rows:
        record_type: RecordTypeEnum | None = record_type_of(row["labels"])
        if record_type is None:
            continue
        superseders: tuple[tuple[str, str], ...] = tuple(
            sorted((item["assertion_id"], item["subject_id"]) for item in row["superseders"])
        )
        found[row["node"]["id"]] = RecordRow(
            node=row["node"],
            record_type=record_type,
            project_key=row["project_key"],
            superseders=superseders,
        )
    return found
