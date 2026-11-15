"""`IRecordReferenceLookup`: what a referenced record is, read on the generic `:Record` label."""

from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.ports.references import IRecordReferenceLookup
from noesis.bounded_context.knowledge.domain.value_objects import (
    RecordId,
    RecordReference,
    SpaceId,
)

from .neo4j_review_record_support import RecordRow, fetch_record_rows
from .neo4j_write_support import TransactionProvider


class Neo4jRecordReferenceLookupAdapter(IRecordReferenceLookup):
    """Describes records inside the unit of work's own transaction."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def describe(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[RecordReference]:
        """One reference per id that exists in `space_id`, in the order given."""
        rows: dict[str, RecordRow] = await fetch_record_rows(
            self._transaction(), space_id, list(dict.fromkeys(ids))
        )
        references: list[RecordReference] = []
        for record_id in dict.fromkeys(ids):
            row: RecordRow | None = rows.get(record_id.value)
            if row is None:
                continue
            project_id: str | None = row.node.get("project_id")
            references.append(
                RecordReference(
                    record_id=record_id,
                    record_type=row.record_type,
                    space_id=space_id,
                    project_id=RecordId(value=project_id) if project_id else None,
                    effective_status=row.effective_status,
                    head_revision=row.node.get("head_revision"),
                )
            )
        return references
