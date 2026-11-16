"""`IRecordChangeLog` over `:ChangeCounter` and `:Change` nodes, in the unit of work's transaction.

The per-space counter is incremented with `SET` in the same transaction as the aggregate write,
so its write lock is held until commit: sequences are commit-ordered and gap-free, writers of
one space are serialised, and a rollback consumes no sequence (verified in C2's record store
capabilities, "Node write lock"). The counter node is created on first use; the statement first
takes the write lock on the space's unique `:Space` node, so concurrent first appends cannot
MERGE two counters even before the `change_feed` uniqueness constraint exists.
"""

from typing import Any, LiteralString
from uuid import uuid4

from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.ports.changes import IRecordChangeLog
from noesis.shared_kernel.contracts.knowledge import RecordChangedContract

from .neo4j_write_support import TransactionProvider

_APPEND: LiteralString = """
MATCH (space:Space {id: $space_id})
SET space._lock = true
REMOVE space._lock
WITH space
MERGE (counter:ChangeCounter {space_id: $space_id})
ON CREATE SET counter.value = 0
SET counter.value = counter.value + 1
CREATE (change:Change {
    change_key: $space_id + ':' + toString(counter.value),
    sequence: counter.value,
    event_id: $event_id,
    space_id: $space_id,
    record_id: $record_id,
    record_type: $record_type,
    change_kind: $change_kind,
    revision: $revision,
    status: $status,
    occurred_at: $occurred_at
})
RETURN change.sequence AS sequence
"""


class Neo4jRecordChangeLogAdapter(IRecordChangeLog):
    """Appends `:Change` nodes through the unit of work's open transaction."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def append(self, change: PendingRecordChange) -> RecordChangedContract:
        """Stage `change` with the next sequence of its space."""
        event_id: str = uuid4().hex
        rows: list[dict[str, Any]] = await self._transaction().run(
            _APPEND,
            {
                "space_id": change.space_id,
                "event_id": event_id,
                "record_id": change.record_id,
                "record_type": change.record_type,
                "change_kind": change.change_kind,
                "revision": change.revision,
                "status": change.status,
                "occurred_at": change.occurred_at,
            },
        )
        return RecordChangedContract(
            event_id=event_id,
            occurred_at=change.occurred_at,
            sequence=rows[0]["sequence"],
            space_id=change.space_id,
            record_id=change.record_id,
            record_type=change.record_type,
            change_kind=change.change_kind,
            revision=change.revision,
            status=change.status,
        )
