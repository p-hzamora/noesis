"""`IConsolidationRepository` over `:Consolidation` and `:ConsolidationMembership` nodes.

Shape: `(m:ConsolidationMembership)-[:OF]->(c:Consolidation)` and
`(m)-[:CONSOLIDATES {at_revision}]->(:Record)`; once materialised, `(c)-[:PRODUCED]->(:Record)`
reaches the successor and each assertion. Nothing here carries the `:Record` label, so a
consolidation is never searchable and never an assertion endpoint.
"""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Consolidation
from noesis.bounded_context.knowledge.domain.repositories import IConsolidationRepository
from noesis.bounded_context.knowledge.domain.value_objects import ConsolidationId, SpaceId
from noesis.exceptions import (
    ConsolidationMembershipConflictError,
    GraphStoreConstraintViolatedError,
    RevisionConflictError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers.consolidation_node_mapper import ConsolidationNodeMapper
from .neo4j_consolidation_support import open_memberships
from .neo4j_write_support import TransactionProvider, already_exists

OPEN_KEY_PROPERTY: str = "open_key"

_CREATE: LiteralString = """
CREATE (consolidation:Consolidation $consolidation)
WITH consolidation
UNWIND $members AS member
MATCH (record:Knowledge {id: member.record_id, space_id: $space_id})
CREATE (membership:ConsolidationMembership)-[:OF]->(consolidation)
SET membership = member
CREATE (membership)-[:CONSOLIDATES {at_revision: member.at_revision}]->(record)
"""
_LOAD: LiteralString = """
MATCH (consolidation:Consolidation {id: $id, space_id: $space_id})
OPTIONAL MATCH (membership:ConsolidationMembership)-[:OF]->(consolidation)
RETURN properties(consolidation) AS node,
       collect(properties(membership)) AS members
"""
# A write takes the node's exclusive lock until the transaction ends; a concurrent decision on
# the same consolidation waits here and then reads the state the previous holder committed.
_LOCK: LiteralString = """
MATCH (consolidation:Consolidation {id: $id, space_id: $space_id})
SET consolidation._lock = true
REMOVE consolidation._lock
RETURN consolidation.id AS id
"""
_SAVE: LiteralString = """
MATCH (consolidation:Consolidation {id: $id, space_id: $space_id})
WHERE consolidation.version = $expected
SET consolidation = $consolidation
RETURN consolidation.id AS id
"""
_RELEASE: LiteralString = """
MATCH (membership:ConsolidationMembership {consolidation_id: $id})
REMOVE membership.open_key
"""
_PRODUCED: LiteralString = """
MATCH (consolidation:Consolidation {id: $id, space_id: $space_id})
UNWIND $ids AS produced_id
MATCH (record:Record {id: produced_id, space_id: $space_id})
MERGE (consolidation)-[:PRODUCED]->(record)
"""
_VERSION: LiteralString = """
MATCH (consolidation:Consolidation {id: $id}) RETURN consolidation.version AS version
"""


class Neo4jConsolidationRepositoryAdapter(IConsolidationRepository):
    """Consolidations inside the unit of work's transaction.

    The client opens a separate short transaction only to name the winner after a constraint
    conflict, because Neo4j ends the failed transaction.
    """

    def __init__(self, transaction: TransactionProvider, client: Neo4jClient) -> None:
        self._transaction: TransactionProvider = transaction
        self._client: Neo4jClient = client

    async def add(self, consolidation: Consolidation) -> None:
        """Stage a new consolidation with one membership per original.

        Raises:
            ConsolidationMembershipConflictError: A member belongs to an open consolidation.
            EntryAlreadyExistsError: The id is taken.
        """
        try:
            await self._transaction().run(
                _CREATE,
                {
                    "space_id": consolidation.space_id.value,
                    "consolidation": ConsolidationNodeMapper.to_properties(consolidation),
                    "members": [
                        ConsolidationNodeMapper.membership_properties(consolidation, member)
                        for member in consolidation.members
                    ],
                },
            )
        except GraphStoreConstraintViolatedError as error:
            if error.metadata.get("property") != OPEN_KEY_PROPERTY:
                raise already_exists(
                    error, what="consolidation", key=consolidation.id.value
                ) from error
            async with await self._client.begin() as reader:
                held = await open_memberships(
                    reader, [m.record_id for m in consolidation.members], consolidation.space_id
                )
            raise ConsolidationMembershipConflictError(
                "A member already belongs to an open consolidation.",
                {
                    "conflicts": [
                        {"record_id": h.record_id, "consolidation_id": h.consolidation_id}
                        for h in held
                    ]
                },
                next_steps=["Run `noesis consolidation show` on the one that holds it."],
            ) from error

    async def get_by_id(
        self, consolidation_id: ConsolidationId, *, space_id: SpaceId
    ) -> Consolidation | None:
        """The consolidation in `space_id`, or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _LOAD, {"id": consolidation_id.value, "space_id": space_id.value}
        )
        if not rows or rows[0]["node"] is None:
            return None
        return ConsolidationNodeMapper.to_entity(rows[0]["node"], rows[0]["members"])

    async def get_for_update(
        self, consolidation_id: ConsolidationId, *, space_id: SpaceId
    ) -> Consolidation | None:
        """Lock the consolidation until the unit of work ends, then read it."""
        locked: list[dict[str, Any]] = await self._transaction().run(
            _LOCK, {"id": consolidation_id.value, "space_id": space_id.value}
        )
        if not locked:
            return None
        return await self.get_by_id(consolidation_id, space_id=space_id)

    async def save(self, consolidation: Consolidation, *, expected_version: int) -> None:
        """Stage the new state; dismissal releases the memberships.

        Raises:
            RevisionConflictError: The stored version is not `expected_version`.
        """
        transaction: Neo4jTransaction = self._transaction()
        saved: list[dict[str, Any]] = await transaction.run(
            _SAVE,
            {
                "id": consolidation.id.value,
                "space_id": consolidation.space_id.value,
                "expected": expected_version,
                "consolidation": ConsolidationNodeMapper.to_properties(consolidation),
            },
        )
        if not saved:
            actual: list[dict[str, Any]] = await transaction.run(
                _VERSION, {"id": consolidation.id.value}
            )
            raise RevisionConflictError(
                f"Expected consolidation version {expected_version} but it is "
                f"{actual[0]['version'] if actual else None}.",
                {
                    "consolidation_id": consolidation.id.value,
                    "expected_version": expected_version,
                    "actual_version": actual[0]["version"] if actual else None,
                },
                next_steps=["Run `noesis consolidation show` and decide again."],
            )
        if not consolidation.holds_membership:
            await transaction.run(_RELEASE, {"id": consolidation.id.value})
        produced: list[str] = [
            *([consolidation.successor_id.value] if consolidation.successor_id else []),
            *(item.value for item in consolidation.produced_assertion_ids),
        ]
        if produced:
            await transaction.run(
                _PRODUCED,
                {
                    "id": consolidation.id.value,
                    "space_id": consolidation.space_id.value,
                    "ids": produced,
                },
            )
