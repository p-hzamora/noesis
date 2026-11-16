"""Cypher the consolidation guard and read adapters share: open memberships and dismissed pairs."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import OpenMembershipDto
from noesis.bounded_context.knowledge.domain.value_objects import (
    DismissedPair,
    RecordId,
    SpaceId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jTransaction

_CONFLICTS: LiteralString = """
MATCH (membership:ConsolidationMembership {space_id: $space_id})
WHERE membership.record_id IN $ids AND membership.open_key IS NOT NULL
RETURN membership.record_id AS record_id, membership.consolidation_id AS consolidation_id
ORDER BY record_id
"""
# A `distinct` dismissal judged every unordered pair of its members at the revisions it pinned.
_DISMISSED_PAIRS: LiteralString = """
MATCH (consolidation:Consolidation {
    space_id: $space_id, state: 'dismissed', dismissal_reason_kind: 'distinct'})
MATCH (first:ConsolidationMembership {consolidation_id: consolidation.id})
MATCH (second:ConsolidationMembership {consolidation_id: consolidation.id})
WHERE first.record_id < second.record_id
  AND first.record_id IN $ids AND second.record_id IN $ids
RETURN consolidation.id AS consolidation_id,
       first.record_id AS first_id, first.at_revision AS first_revision,
       second.record_id AS second_id, second.at_revision AS second_revision
ORDER BY consolidation_id, first_id, second_id
"""


async def open_memberships(
    transaction: Neo4jTransaction, record_ids: Sequence[RecordId], space_id: SpaceId
) -> list[OpenMembershipDto]:
    """The records among `record_ids` that an open consolidation holds."""
    rows: list[dict[str, Any]] = await transaction.run(
        _CONFLICTS, {"space_id": space_id.value, "ids": [item.value for item in record_ids]}
    )
    return [
        OpenMembershipDto(record_id=row["record_id"], consolidation_id=row["consolidation_id"])
        for row in rows
    ]


async def dismissed_pairs(
    transaction: Neo4jTransaction, record_ids: Sequence[RecordId], space_id: SpaceId
) -> list[DismissedPair]:
    """`distinct` dismissals that judged two of `record_ids`, with the revisions they judged."""
    rows: list[dict[str, Any]] = await transaction.run(
        _DISMISSED_PAIRS, {"space_id": space_id.value, "ids": [item.value for item in record_ids]}
    )
    return [
        DismissedPair(
            consolidation_id=row["consolidation_id"],
            first_id=row["first_id"],
            first_revision=row["first_revision"],
            second_id=row["second_id"],
            second_revision=row["second_revision"],
        )
        for row in rows
    ]
