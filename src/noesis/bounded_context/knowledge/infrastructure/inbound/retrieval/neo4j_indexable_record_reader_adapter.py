"""Body reader (structural `IIndexableRecordReader`): the only path a body leaves Knowledge."""

from typing import Any, LiteralString

from noesis.exceptions import RecordNotFoundError
from noesis.shared_kernel.contracts.knowledge import IndexableRecordContract, RecordBodyMissingError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .record_node_contracts import NodeProperties, ownership_of

_KNOWLEDGE: LiteralString = """
MATCH (record:Knowledge {id: $id, space_id: $space_id})
MATCH (revision:Revision {
    revision_key: record.id + ':' + toString(coalesce($revision, record.head_revision))
})
RETURN properties(record) AS record, properties(revision) AS revision
"""
_EXPERIENCE: LiteralString = """
MATCH (record:Experience {id: $id, space_id: $space_id})
RETURN properties(record) AS record
"""


class Neo4jIndexableRecordReaderAdapter:
    """Reads one revision (Knowledge) or one Experience with its text."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get(
        self, record_id: str, revision: int | None, *, space_id: str
    ) -> IndexableRecordContract:
        """The record revision with its title and body.

        A null `revision` on Knowledge means the head; an Experience has no revisions.

        Raises:
            RecordNotFoundError: No such record or revision in the space.
            RecordBodyMissingError: The revision is file-owned and has no body.
        """
        parameters: dict[str, Any] = {"id": record_id, "space_id": space_id, "revision": revision}
        async with await self._client.begin() as transaction:
            knowledge: list[dict[str, Any]] = await transaction.run(_KNOWLEDGE, parameters)
            experience: list[dict[str, Any]] = (
                [] if knowledge else await transaction.run(_EXPERIENCE, parameters)
            )
        if knowledge:
            return _knowledge_contract(knowledge[0]["record"], knowledge[0]["revision"])
        if experience:
            return _experience_contract(experience[0]["record"])
        raise RecordNotFoundError(
            f"No record {record_id} (revision {revision}) in space {space_id}.",
            {"record_id": record_id, "revision": revision, "space_id": space_id},
        )


def _knowledge_contract(
    record: NodeProperties, revision: NodeProperties
) -> IndexableRecordContract:
    if "body" not in revision:
        raise RecordBodyMissingError(
            f"Revision {revision['number']} of {record['id']} has no body (file-owned)."
        )
    return IndexableRecordContract(
        record_id=record["id"],
        record_type="knowledge",
        subtype=record.get("subtype"),
        ownership=ownership_of("knowledge", record),
        revision=revision["number"],
        head_revision=record["head_revision"],
        status=record.get("status"),
        project_id=record.get("project_id"),
        tags=tuple(sorted(record.get("tags", []))),
        title=revision.get("title"),
        body=revision["body"],
        revised_at=revision["created_at"],
    )


def _experience_contract(record: NodeProperties) -> IndexableRecordContract:
    return IndexableRecordContract(
        record_id=record["id"],
        record_type="experience",
        subtype=record.get("subtype"),
        ownership=ownership_of("experience", record),
        project_id=record.get("project_id"),
        tags=(),
        body=record["body"],
        revised_at=record["created_at"],
    )
