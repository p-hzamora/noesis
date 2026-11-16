"""The `probe` projection: tests only, never imported by `src/` (D-025).

One entry per Knowledge or Experience record at its head revision. Two variants share the same
behaviour: in memory (unit tests) and in Neo4j as `:IndexProbe` nodes (integration and e2e).
"""

import asyncio
from typing import LiteralString

from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    IIndexWriter,
    ProjectionEntryDto,
)
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

PROBE_KIND: str = "probe"
PROBE_PROFILE: dict[str, JsonValue] = {"name": "probe", "version": 1}

UPSERT_PROBE: LiteralString = """
MERGE (p:IndexProbe {key: $key})
SET p.space_id = $space_id,
    p.record_id = $record_id,
    p.revision = $revision,
    p.status = $status
"""
CLEAR_PROBES: LiteralString = "MATCH (p:IndexProbe {space_id: $space_id}) DELETE p"
READ_PROBES: LiteralString = """
MATCH (p:IndexProbe {space_id: $space_id})
RETURN p.record_id AS record_id, p.revision AS revision
"""


class InMemoryProbeProjection(IIndexWriter):
    """Keeps `(revision, status)` per space and record; remembers every call."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, tuple[int | None, str | None]]] = {}
        self.upserts: list[ProjectionEntryDto] = []
        self.clears: list[str] = []

    @property
    def kind(self) -> str:
        """Always `probe`."""
        return PROBE_KIND

    def status_of(self, space_id: str, record_id: str) -> str | None:
        """The stored status of an entry (test inspection)."""
        return self._entries[space_id][record_id][1]

    def drop(self, space_id: str, record_id: str) -> None:
        """Test setup: remove one entry behind the handlers' back."""
        del self._entries[space_id][record_id]

    def plant(self, space_id: str, record_id: str, revision: int | None) -> None:
        """Test setup: add an entry no change produced."""
        self._entries.setdefault(space_id, {})[record_id] = (revision, None)

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Replace the record's entry, whatever revision it held."""
        self.upserts.append(entry)
        self._entries.setdefault(entry.space_id, {})[entry.key.record_id] = (
            entry.key.revision,
            entry.record.status,
        )

    async def clear(self, space_id: str) -> None:
        """Drop every entry of the space."""
        self.clears.append(space_id)
        self._entries.pop(space_id, None)

    def profile(self) -> dict[str, JsonValue]:
        """`{"name": "probe", "version": 1}`."""
        return dict(PROBE_PROFILE)

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """record id to stored revision."""
        return {rid: revision for rid, (revision, _) in self._entries.get(space_id, {}).items()}


class Neo4jProbeProjection(IIndexWriter):
    """`:IndexProbe {key, space_id, record_id, revision, status}` merged on `key`.

    Args:
        client: The shared Neo4j client; each call opens its own transaction.
        delay_ms: Pause after each committed upsert, so a test can kill a sync mid-batch.
    """

    def __init__(self, client: Neo4jClient, delay_ms: int = 0) -> None:
        self._client: Neo4jClient = client
        self._delay_ms: int = delay_ms

    @property
    def kind(self) -> str:
        """Always `probe`."""
        return PROBE_KIND

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """MERGE the node on `<space_id>:<record_id>`, then wait `delay_ms`."""
        async with await self._client.begin() as transaction:
            await transaction.run(
                UPSERT_PROBE,
                {
                    "key": f"{entry.space_id}:{entry.key.record_id}",
                    "space_id": entry.space_id,
                    "record_id": entry.key.record_id,
                    "revision": entry.key.revision,
                    "status": entry.record.status,
                },
            )
            await transaction.commit()
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000)

    async def clear(self, space_id: str) -> None:
        """Delete every `:IndexProbe` of the space."""
        async with await self._client.begin() as transaction:
            await transaction.run(CLEAR_PROBES, {"space_id": space_id})
            await transaction.commit()

    def profile(self) -> dict[str, JsonValue]:
        """`{"name": "probe", "version": 1}`."""
        return dict(PROBE_PROFILE)

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """record id to stored revision (None for an Experience)."""
        async with await self._client.begin() as transaction:
            rows = await transaction.run(READ_PROBES, {"space_id": space_id})
        return {row["record_id"]: row["revision"] for row in rows}
