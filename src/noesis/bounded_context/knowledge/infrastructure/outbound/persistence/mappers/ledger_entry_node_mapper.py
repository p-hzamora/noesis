"""`LedgerEntry` <-> `:IdempotencyKey` node."""

import json

from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId

from .node_keys import ledger_key
from .node_properties import NodeProperties, without_nulls


class LedgerEntryNodeMapper:
    """Maps a ledger entry to its node properties and back.

    `extra` is a map, which Neo4j cannot store as a property, so it is kept as JSON text.
    """

    @staticmethod
    def to_properties(entry: LedgerEntry) -> NodeProperties:
        """Properties of the `:IdempotencyKey` node."""
        return without_nulls(
            {
                "key": ledger_key(entry.space_id, entry.key),
                "space_id": entry.space_id.value,
                "idempotency_key": entry.key,
                "command": entry.command,
                "fingerprint": entry.fingerprint,
                "record_id": entry.record_id.value if entry.record_id else None,
                "revision": entry.revision,
                "extra": json.dumps(entry.extra, sort_keys=True, separators=(",", ":")),
                "recorded_at": entry.recorded_at,
            }
        )

    @staticmethod
    def to_entry(node: NodeProperties) -> LedgerEntry:
        """The ledger entry a node stores."""
        record_id: str | None = node.get("record_id")
        return LedgerEntry(
            space_id=SpaceId(value=node["space_id"]),
            key=node["idempotency_key"],
            command=node["command"],
            fingerprint=node["fingerprint"],
            record_id=RecordId(value=record_id) if record_id else None,
            revision=node.get("revision"),
            extra=json.loads(node["extra"]),
            recorded_at=node["recorded_at"],
        )
