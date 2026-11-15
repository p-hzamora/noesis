"""`IImportCandidateReadRepository` over the record nodes, scoped to one space."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import (
    ImportCandidateDto,
    ImportCandidatesDto,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IImportCandidateReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    IdHolderEnum,
    OwnershipEnum,
    RecordId,
    SpaceId,
    Tag,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

_ID_HOLDER: LiteralString = """
MATCH (record:Record {id: $record_id, space_id: $space_id})
RETURN labels(record) AS labels, record.ownership AS ownership
"""
# two branches, each anchored on an indexed node: the declared id, or the file Source's locator
_CANDIDATES: LiteralString = """
CALL () {
  MATCH (k:Knowledge {id: $record_id, space_id: $space_id})
  RETURN k
  UNION
  MATCH (:Source {space_id: $space_id, kind: 'file_version', locator: $locator})
        <-[:FROM_SOURCE]-(:Revision)-[:REVISION_OF]->(k:Knowledge {space_id: $space_id})
  WHERE $origin_tag IN k.tags
  RETURN k
}
MATCH (head:Revision {revision_key: k.id + ':' + toString(k.head_revision)})
OPTIONAL MATCH (head)-[:FROM_SOURCE]->(file:Source {kind: 'file_version'})
WITH k, head, collect(file.digest) AS digests
RETURN properties(k) AS knowledge, properties(head) AS head, digests
"""


class Neo4jImportCandidateReadRepositoryAdapter(IImportCandidateReadRepository):
    """One read transaction per note: the id holder, then the candidates."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def find_candidates(
        self, record_id: RecordId | None, locator: str, origin_tag: Tag, *, space_id: SpaceId
    ) -> ImportCandidatesDto:
        """The id holder and the Knowledge records that have the id or cite the locator."""
        async with await self._client.begin() as transaction:
            holder: IdHolderEnum = IdHolderEnum.NONE
            if record_id is not None:
                held: list[dict[str, Any]] = await transaction.run(
                    _ID_HOLDER, {"record_id": record_id.value, "space_id": space_id.value}
                )
                if held:
                    holder = (
                        IdHolderEnum.GRAPH_KNOWLEDGE
                        if "Knowledge" in held[0]["labels"]
                        and held[0]["ownership"] == OwnershipEnum.GRAPH.value
                        else IdHolderEnum.OTHER
                    )
            rows: list[dict[str, Any]] = await transaction.run(
                _CANDIDATES,
                {
                    "record_id": record_id.value if record_id is not None else None,
                    "locator": locator,
                    "origin_tag": origin_tag.value,
                    "space_id": space_id.value,
                },
            )
        return ImportCandidatesDto(
            id_holder=holder.value, candidates=tuple(_candidate(row) for row in rows)
        )


def _candidate(row: dict[str, Any]) -> ImportCandidateDto:
    knowledge: dict[str, Any] = row["knowledge"]
    head: dict[str, Any] = row["head"]
    return ImportCandidateDto(
        id=knowledge["id"],
        status=knowledge["status"],
        created_at=knowledge["created_at"],
        head_revision=knowledge["head_revision"],
        title=head["title"],
        body=head.get("body"),
        head_file_digests=tuple(row["digests"]),
    )
