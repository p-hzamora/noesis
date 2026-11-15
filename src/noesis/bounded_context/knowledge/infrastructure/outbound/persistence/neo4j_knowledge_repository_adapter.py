"""`IKnowledgeRepository` over `:Record:Knowledge` nodes and their `:Revision` nodes.

Shape: `(k:Record:Knowledge)-[:IN_SPACE]->(:Space)`, `(k)-[:BELONGS_TO_PROJECT]->(:Project)`,
`(r:Revision)-[:REVISION_OF]->(k)`, `(r)-[:FROM_SOURCE]->(:Source)`. The record keeps
`head_revision`; each revision is its own immutable node keyed `<record_id>:<number>`.
"""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.repositories import IKnowledgeRepository
from noesis.bounded_context.knowledge.domain.value_objects import (
    FileContent,
    RecordId,
    Revision,
    SpaceId,
)
from noesis.exceptions import GraphStoreConstraintViolatedError, RevisionConflictError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers import KnowledgeNodeMapper, revision_key
from .neo4j_review_write_support import stage_decision
from .neo4j_write_support import TransactionProvider, create_unique, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
CREATE (knowledge:Record:Knowledge $knowledge)-[:IN_SPACE]->(space)
CREATE (revision:Revision $revision)-[:REVISION_OF]->(knowledge)
"""
_LINK_PROJECT: LiteralString = """
MATCH (knowledge:Knowledge {id: $id}), (project:Project {id: $project_id})
CREATE (knowledge)-[:BELONGS_TO_PROJECT]->(project)
"""
_LINK_SOURCES: LiteralString = """
MATCH (revision:Revision {revision_key: $revision_key})
UNWIND $source_ids AS source_id
MATCH (source:Source {id: source_id})
CREATE (revision)-[:FROM_SOURCE]->(source)
"""
_LOAD: LiteralString = """
MATCH (knowledge:Knowledge {id: $id, space_id: $space_id})
MATCH (head:Revision {revision_key: knowledge.id + ':' + toString(knowledge.head_revision)})
RETURN properties(knowledge) AS knowledge, properties(head) AS head
"""
# A write takes the node's exclusive lock until the transaction ends; setting and removing a
# marker leaves no property behind (verified against the pinned image). Reads after it see the
# head the previous holder committed.
_LOCK: LiteralString = """
MATCH (knowledge:Knowledge {id: $id, space_id: $space_id})
SET knowledge._lock = true
REMOVE knowledge._lock
RETURN knowledge.id AS id
"""
_APPEND: LiteralString = """
MATCH (knowledge:Knowledge {id: $id, space_id: $space_id})
WHERE knowledge.head_revision = $previous
CREATE (revision:Revision $revision)-[:REVISION_OF]->(knowledge)
SET knowledge.head_revision = $number, knowledge.updated_at = $updated_at
RETURN knowledge.id AS id
"""
_SAVE_REVIEW: LiteralString = """
MATCH (knowledge:Knowledge {id: $id, space_id: $space_id})
SET knowledge.status = $status, knowledge.decision_seq = $decision_seq,
    knowledge.superseded_by_assertion_id = $superseded_by, knowledge.updated_at = $updated_at
RETURN knowledge.id AS id
"""
_HEAD: LiteralString = (
    "MATCH (knowledge:Knowledge {id: $id}) RETURN knowledge.head_revision AS head"
)


class Neo4jKnowledgeRepositoryAdapter(IKnowledgeRepository):
    """Knowledge and its revisions; the `Revision.revision_key` constraint guards the head.

    The client opens a separate short transaction only to report the actual head after a
    constraint conflict, because Neo4j ends the failed transaction.
    """

    def __init__(self, transaction: TransactionProvider, client: Neo4jClient) -> None:
        self._transaction: TransactionProvider = transaction
        self._client: Neo4jClient = client

    async def add(self, knowledge: Knowledge) -> None:
        """Stage new knowledge with its revision 1.

        Raises:
            ReferenceNotInSpaceError: The space, project or a source is not in the space.
            EntryAlreadyExistsError: The id is taken.
        """
        transaction: Neo4jTransaction = self._transaction()
        project_id: RecordId | None = knowledge.applicability.project_id
        await require_references(
            transaction,
            space_id=knowledge.space_id,
            project_id=project_id,
            source_ids=_cited(knowledge.head),
        )
        await create_unique(
            transaction,
            _CREATE,
            {
                "space_id": knowledge.space_id.value,
                "knowledge": KnowledgeNodeMapper.to_properties(knowledge),
                "revision": KnowledgeNodeMapper.to_revision_properties(
                    knowledge.id, knowledge.head
                ),
            },
            what="knowledge",
            key=knowledge.id.value,
        )
        if project_id is not None:
            await transaction.run(
                _LINK_PROJECT, {"id": knowledge.id.value, "project_id": project_id.value}
            )
        await self._link_sources(transaction, knowledge.id, knowledge.head)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        """The knowledge with this id in `space_id`, or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _LOAD, {"id": record_id.value, "space_id": space_id.value}
        )
        return (
            KnowledgeNodeMapper.to_entity(rows[0]["knowledge"], rows[0]["head"]) if rows else None
        )

    async def get_for_update(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        """Lock the record node until the unit of work ends, then read it (A-13).

        A concurrent caller waits on the lock and then reads the head this one committed.
        """
        locked: list[dict[str, Any]] = await self._transaction().run(
            _LOCK, {"id": record_id.value, "space_id": space_id.value}
        )
        if not locked:
            return None
        return await self.get(record_id, space_id=space_id)

    async def save(self, knowledge: Knowledge) -> None:
        """Stage the status, `decision_seq`, superseding assertion and the latest decision.

        Raises:
            StatusConflictError: A decision with the same key exists.
        """
        transaction: Neo4jTransaction = self._transaction()
        await transaction.run(
            _SAVE_REVIEW,
            {
                "id": knowledge.id.value,
                "space_id": knowledge.space_id.value,
                "status": knowledge.status.value,
                "decision_seq": knowledge.decision_seq,
                "superseded_by": (
                    knowledge.superseded_by_assertion_id.value
                    if knowledge.superseded_by_assertion_id
                    else None
                ),
                "updated_at": knowledge.updated_at,
            },
        )
        if knowledge.latest_decision is not None:
            await stage_decision(
                transaction,
                space_id=knowledge.space_id,
                record_id=knowledge.id,
                decision=knowledge.latest_decision,
            )

    async def append_revision(self, knowledge: Knowledge, revision: Revision) -> None:
        """Stage `revision` as the new head, moving `head_revision` from n-1 to n.

        Raises:
            RevisionConflictError: The stored head is not n-1, or revision n already exists;
                metadata has the expected and actual head.
        """
        transaction: Neo4jTransaction = self._transaction()
        await require_references(
            transaction, space_id=knowledge.space_id, source_ids=_cited(revision)
        )
        try:
            appended: list[dict[str, Any]] = await transaction.run(
                _APPEND,
                {
                    "id": knowledge.id.value,
                    "space_id": knowledge.space_id.value,
                    "previous": revision.number - 1,
                    "number": revision.number,
                    "updated_at": knowledge.updated_at,
                    "revision": KnowledgeNodeMapper.to_revision_properties(knowledge.id, revision),
                },
            )
        except GraphStoreConstraintViolatedError as error:
            async with await self._client.begin() as reader:
                raise await self._conflict(reader, knowledge.id, revision) from error
        if not appended:
            raise await self._conflict(transaction, knowledge.id, revision)
        await self._link_sources(transaction, knowledge.id, revision)

    async def _link_sources(
        self, transaction: Neo4jTransaction, record_id: RecordId, revision: Revision
    ) -> None:
        await transaction.run(
            _LINK_SOURCES,
            {
                "revision_key": revision_key(record_id, revision.number),
                "source_ids": [source_id.value for source_id in revision.source_ids],
            },
        )

    @staticmethod
    async def _conflict(
        transaction: Neo4jTransaction, record_id: RecordId, revision: Revision
    ) -> RevisionConflictError:
        rows: list[dict[str, Any]] = await transaction.run(_HEAD, {"id": record_id.value})
        actual: int | None = rows[0]["head"] if rows else None
        expected: int = revision.number - 1
        return RevisionConflictError(
            f"Expected revision {expected} but the head is {actual}.",
            {
                "record_id": record_id.value,
                "expected_revision": expected,
                "actual_revision": actual,
            },
            next_steps=["Run `noesis record get`, re-apply the change, retry."],
        )


def _cited(revision: Revision) -> tuple[RecordId, ...]:
    """Every source a revision references, its file_version source included."""
    extra: tuple[RecordId, ...] = (
        (revision.content.file_version_source_id,)
        if isinstance(revision.content, FileContent)
        else ()
    )
    return tuple(dict.fromkeys((*revision.source_ids, *extra)))
