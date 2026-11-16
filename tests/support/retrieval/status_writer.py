"""Test-only stand-in for C4's transitions: set a record's status and append `status_changed`.

C4 is not built, so nothing in `src/` changes a Knowledge status. This helper does what a C4
transition will do: in ONE Knowledge unit of work it sets the record's stored `status` and appends
a `status_changed` change through `uow.changes`, so the change feed carries the transition (AC-032).
"""

import asyncio
from datetime import datetime
from typing import LiteralString

from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    Neo4jKnowledgeUnitOfWorkAdapter,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

_SET_STATUS: LiteralString = """
MATCH (k:Knowledge {id: $record_id, space_id: $space_id})
SET k.status = $status
RETURN k.head_revision AS head_revision
"""


async def set_status(
    client: Neo4jClient, *, space_id: str, record_id: str, status: str, occurred_at: datetime
) -> int:
    """Set `status` on a Knowledge record and append its `status_changed` change, atomically.

    Returns:
        The sequence assigned to the appended change.

    Raises:
        LookupError: The record is not Knowledge in `space_id` (nothing was written).
    """
    async with Neo4jKnowledgeUnitOfWorkAdapter(client) as uow:
        rows = await uow._current().run(
            _SET_STATUS, {"record_id": record_id, "space_id": space_id, "status": status}
        )
        if not rows:
            raise LookupError(f"no Knowledge {record_id} in space {space_id}")
        change = await uow.changes.append(
            PendingRecordChange(
                space_id=space_id,
                record_id=record_id,
                record_type="knowledge",
                change_kind="status_changed",
                revision=rows[0]["head_revision"],
                status=status,
                occurred_at=occurred_at,
            )
        )
        await uow.commit()
    return change.sequence


def set_status_blocking(
    settings: Neo4jConnectionSettings,
    *,
    space_id: str,
    record_id: str,
    status: str,
    occurred_at: datetime,
) -> int:
    """`set_status` for a synchronous test: opens its own client and closes it."""

    async def run() -> int:
        async with Neo4jClient(settings) as client:
            return await set_status(
                client,
                space_id=space_id,
                record_id=record_id,
                status=status,
                occurred_at=occurred_at,
            )

    return asyncio.run(run())
