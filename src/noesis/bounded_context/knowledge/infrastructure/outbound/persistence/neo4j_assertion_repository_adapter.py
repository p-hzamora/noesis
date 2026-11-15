"""`IAssertionRepository` over `:Record:Assertion` nodes and their `:Decision` nodes.

Shape: `(a:Record:Assertion)-[:IN_SPACE]->(:Space)`, `(a)-[:SUBJECT {at_revision}]->(:Record)`,
`(a)-[:OBJECT {at_revision}]->(:Record)`, `(a)-[:EVIDENCED_BY]->(:Record)`,
`(a)-[:FROM_SOURCE]->(:Source)`, `(a)-[:BELONGS_TO_PROJECT]->(:Project)`. `live_key` is set only
while the assertion is `proposed` or `accepted` and removed once it is retracted or superseded,
which frees the statement (the uniqueness constraint ignores nodes without the property).
"""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Assertion
from noesis.bounded_context.knowledge.domain.repositories import IAssertionRepository
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId, StatementKey
from noesis.exceptions import (
    DuplicateAssertionError,
    GraphStoreConstraintViolatedError,
    ReferenceNotInSpaceError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers import AssertionNodeMapper, is_live, live_key
from .neo4j_review_write_support import LIVE_KEY_PROPERTY, stage_decision
from .neo4j_write_support import TransactionProvider, already_exists, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
MATCH (subject:Record {id: $subject_id, space_id: $space_id})
MATCH (target:Record {id: $object_id, space_id: $space_id})
CREATE (assertion:Record:Assertion $assertion)-[:IN_SPACE]->(space)
CREATE (assertion)-[:SUBJECT {at_revision: $subject_at_revision}]->(subject)
CREATE (assertion)-[:OBJECT {at_revision: $object_at_revision}]->(target)
RETURN assertion.id AS id
"""
_LINK_EVIDENCE: LiteralString = """
MATCH (assertion:Assertion {id: $id})
UNWIND $evidence_ids AS evidence_id
MATCH (evidence:Record {id: evidence_id, space_id: $space_id})
CREATE (assertion)-[:EVIDENCED_BY]->(evidence)
"""
_LINK_SOURCES: LiteralString = """
MATCH (assertion:Assertion {id: $id})
UNWIND $source_ids AS source_id
MATCH (source:Source {id: source_id, space_id: $space_id})
CREATE (assertion)-[:FROM_SOURCE]->(source)
"""
_LINK_PROJECT: LiteralString = """
MATCH (assertion:Assertion {id: $id}), (project:Project {id: $project_id})
CREATE (assertion)-[:BELONGS_TO_PROJECT]->(project)
"""
_LOAD: LiteralString = """
MATCH (assertion:Assertion {id: $id, space_id: $space_id})
MATCH (assertion)-[subject:SUBJECT]->(:Record)
MATCH (assertion)-[object:OBJECT]->(:Record)
RETURN properties(assertion) AS assertion, subject.at_revision AS subject_at_revision,
       object.at_revision AS object_at_revision
"""
_LOAD_LIVE: LiteralString = (
    "MATCH (assertion:Assertion {live_key: $live_key}) RETURN assertion.id AS id"
)
_SAVE_LIVE: LiteralString = """
MATCH (assertion:Assertion {id: $id, space_id: $space_id})
SET assertion.status = $status, assertion.decision_seq = $decision_seq,
    assertion.superseded_by_assertion_id = $superseded_by, assertion.updated_at = $updated_at
RETURN assertion.id AS id
"""
_SAVE_RETIRED: LiteralString = """
MATCH (assertion:Assertion {id: $id, space_id: $space_id})
SET assertion.status = $status, assertion.decision_seq = $decision_seq,
    assertion.superseded_by_assertion_id = $superseded_by, assertion.updated_at = $updated_at
REMOVE assertion.live_key
RETURN assertion.id AS id
"""


class Neo4jAssertionRepositoryAdapter(IAssertionRepository):
    """Assertions and their review state.

    The client opens a separate short transaction only to name the winner of a `live_key`
    race, because Neo4j ends the failed transaction.
    """

    def __init__(self, transaction: TransactionProvider, client: Neo4jClient) -> None:
        self._transaction: TransactionProvider = transaction
        self._client: Neo4jClient = client
        self._staged_live_keys: list[str] = []

    async def add(self, assertion: Assertion) -> None:
        """Stage a new assertion with its edges.

        Raises:
            ReferenceNotInSpaceError: A project, source, subject or object is not in the space.
            EntryAlreadyExistsError: The id is taken.
            DuplicateAssertionError: A live identical statement exists; metadata has its id.
        """
        transaction: Neo4jTransaction = self._transaction()
        project_id: RecordId | None = assertion.applicability.project_id
        await require_references(
            transaction,
            space_id=assertion.space_id,
            project_id=project_id,
            source_ids=assertion.source_ids,
        )
        properties = AssertionNodeMapper.to_properties(assertion)
        try:
            created: list[dict[str, Any]] = await transaction.run(
                _CREATE,
                {
                    "space_id": assertion.space_id.value,
                    "subject_id": assertion.subject_id.value,
                    "object_id": assertion.object_id.value,
                    "assertion": properties,
                    "subject_at_revision": assertion.subject_at_revision,
                    "object_at_revision": assertion.object_at_revision,
                },
            )
        except GraphStoreConstraintViolatedError as error:
            if error.metadata.get("property") == LIVE_KEY_PROPERTY:
                raise await self.duplicate_error(properties["live_key"]) from error
            raise already_exists(error, what="assertion", key=assertion.id.value) from error
        if not created:
            raise ReferenceNotInSpaceError(
                "The subject or object of the assertion does not exist in this space.",
                {
                    "subject_id": assertion.subject_id.value,
                    "object_id": assertion.object_id.value,
                },
                next_steps=["Check the ids and the active space."],
            )
        if "live_key" in properties:
            self._staged_live_keys.append(properties["live_key"])
        parameters: dict[str, Any] = {
            "id": assertion.id.value,
            "space_id": assertion.space_id.value,
        }
        await transaction.run(
            _LINK_EVIDENCE,
            {**parameters, "evidence_ids": [item.value for item in assertion.evidence_ids]},
        )
        await transaction.run(
            _LINK_SOURCES,
            {**parameters, "source_ids": [item.value for item in assertion.source_ids]},
        )
        if project_id is not None:
            await transaction.run(_LINK_PROJECT, {**parameters, "project_id": project_id.value})

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> Assertion | None:
        """The assertion with this id in `space_id`, or None."""
        return await self._load(
            self._transaction(), _LOAD, {"id": record_id.value, "space_id": space_id.value}
        )

    async def get_live_by_statement(self, key: StatementKey) -> Assertion | None:
        """The `proposed` or `accepted` assertion stating `key`, or None."""
        transaction: Neo4jTransaction = self._transaction()
        rows: list[dict[str, Any]] = await transaction.run(_LOAD_LIVE, {"live_key": live_key(key)})
        if not rows:
            return None
        return await self.get_by_id(RecordId(value=rows[0]["id"]), space_id=key.space_id)

    async def save(self, assertion: Assertion) -> None:
        """Stage the status, `decision_seq` and latest decision; a retired assertion frees its key.

        Raises:
            StatusConflictError: A decision with the same key exists.
        """
        transaction: Neo4jTransaction = self._transaction()
        await transaction.run(
            _SAVE_LIVE if is_live(assertion) else _SAVE_RETIRED,
            {
                "id": assertion.id.value,
                "space_id": assertion.space_id.value,
                "status": assertion.status.value,
                "decision_seq": assertion.decision_seq,
                "superseded_by": (
                    assertion.superseded_by_assertion_id.value
                    if assertion.superseded_by_assertion_id
                    else None
                ),
                "updated_at": assertion.updated_at,
            },
        )
        if assertion.latest_decision is not None:
            await stage_decision(
                transaction,
                space_id=assertion.space_id,
                record_id=assertion.id,
                decision=assertion.latest_decision,
            )

    async def duplicate_error(self, live: str | None = None) -> DuplicateAssertionError:
        """The error naming the live assertion that holds `live` (or any key staged here)."""
        keys: list[str] = [live] if live else list(self._staged_live_keys)
        existing: str | None = None
        async with await self._client.begin() as reader:
            for key in keys:
                rows: list[dict[str, Any]] = await reader.run(_LOAD_LIVE, {"live_key": key})
                if rows:
                    existing = rows[0]["id"]
                    break
        return DuplicateAssertionError(
            f"Assertion {existing} already states the same."
            if existing
            else "A live assertion already states the same.",
            {"existing_id": existing},
            next_steps=["Use the existing assertion id."],
        )

    @staticmethod
    async def _load(
        transaction: Neo4jTransaction, query: LiteralString, parameters: dict[str, Any]
    ) -> Assertion | None:
        rows: list[dict[str, Any]] = await transaction.run(query, parameters)
        if not rows:
            return None
        return AssertionNodeMapper.to_entity(
            rows[0]["assertion"],
            subject_at_revision=rows[0]["subject_at_revision"],
            object_at_revision=rows[0]["object_at_revision"],
        )
