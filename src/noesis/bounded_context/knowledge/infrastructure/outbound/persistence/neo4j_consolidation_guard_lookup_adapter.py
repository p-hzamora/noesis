"""`IConsolidationGuardLookup` inside the unit of work's own transaction."""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import OpenMembershipDto
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationGuardLookup,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    DismissedPair,
    RecordId,
    SpaceId,
)

from .neo4j_consolidation_support import dismissed_pairs, open_memberships
from .neo4j_write_support import TransactionProvider

_EVIDENCE: LiteralString = """
MATCH (object:Knowledge {id: $id, space_id: $space_id})
OPTIONAL MATCH (head:Revision {revision_key: object.id + ':' + toString(object.head_revision)})
WITH object, head
OPTIONAL MATCH (support:Assertion {space_id: $space_id, predicate: 'supports', object_id: $id})
WHERE support.live_key IS NOT NULL
RETURN coalesce(head.source_ids, []) AS source_ids, collect(DISTINCT support.subject_id) AS subjects
"""


class Neo4jConsolidationGuardLookupAdapter(IConsolidationGuardLookup):
    """Reads in the transaction that will write, so a guard and its write see the same graph."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def conflicts(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[OpenMembershipDto]:
        """The records among `record_ids` that an open consolidation holds."""
        return await open_memberships(self._transaction(), record_ids, space_id)

    async def dismissed_pairs(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[DismissedPair]:
        """`distinct` dismissals that judged two of `record_ids`."""
        return await dismissed_pairs(self._transaction(), record_ids, space_id)

    async def evidence_for(
        self, object_id: RecordId, exclude: Sequence[RecordId], space_id: SpaceId
    ) -> list[RecordId]:
        """Head-revision Sources and live `supports` subjects, never the `exclude` records."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _EVIDENCE, {"id": object_id.value, "space_id": space_id.value}
        )
        if not rows:
            return []
        skipped: set[str] = {item.value for item in exclude}
        found: set[str] = {*rows[0]["source_ids"], *rows[0]["subjects"]} - skipped
        return [RecordId(value=item) for item in sorted(found)]
