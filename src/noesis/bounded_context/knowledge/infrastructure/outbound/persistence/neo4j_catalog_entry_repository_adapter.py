"""`ICatalogEntryRepository` over `:Record:CatalogEntry` nodes and their `:Revision` nodes.

Shape: `(e:Record:CatalogEntry)-[:IN_SPACE]->(:Space)`, `(r:Revision)-[:REVISION_OF]->(e)`,
`(r)-[:FROM_SOURCE]->(:Source)`. The entry keeps `head_revision`; each revision is its own
immutable node keyed `<record_id>:<number>`. `CatalogEntry.catalog_key` is unique, so two
first registrations of one kind and name cannot both win.
"""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.repositories import ICatalogEntryRepository
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogRevision,
    RecordId,
    SpaceId,
)
from noesis.exceptions import (
    CatalogEntryAlreadyExistsError,
    GraphStoreConstraintViolatedError,
    RevisionConflictError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

from .mappers import CatalogEntryNodeMapper, catalog_key, revision_key
from .neo4j_write_support import TransactionProvider, already_exists, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
CREATE (entry:Record:CatalogEntry $entry)-[:IN_SPACE]->(space)
CREATE (revision:Revision:CatalogRevision $revision)-[:REVISION_OF]->(entry)
"""
_LINK_SOURCES: LiteralString = """
MATCH (revision:Revision {revision_key: $revision_key})
UNWIND $source_ids AS source_id
MATCH (source:Source {id: source_id})
CREATE (revision)-[:FROM_SOURCE]->(source)
"""
_BY_ID: LiteralString = """
MATCH (entry:CatalogEntry {id: $id, space_id: $space_id})
RETURN properties(entry) AS entry,
       [(revision:Revision)-[:REVISION_OF]->(entry) | properties(revision)] AS revisions
"""
_BY_KEY: LiteralString = """
MATCH (entry:CatalogEntry {catalog_key: $catalog_key})
RETURN properties(entry) AS entry,
       [(revision:Revision)-[:REVISION_OF]->(entry) | properties(revision)] AS revisions
"""
# A write takes the node's exclusive lock until the transaction ends (see the knowledge adapter).
_LOCK: LiteralString = """
MATCH (entry:CatalogEntry {id: $id, space_id: $space_id})
SET entry._lock = true
REMOVE entry._lock
RETURN entry.id AS id
"""
_APPEND: LiteralString = """
MATCH (entry:CatalogEntry {id: $id, space_id: $space_id})
WHERE entry.head_revision = $previous
CREATE (revision:Revision:CatalogRevision $revision)-[:REVISION_OF]->(entry)
SET entry.head_revision = $number, entry.updated_at = $updated_at
RETURN entry.id AS id
"""
_HEAD: LiteralString = "MATCH (entry:CatalogEntry {id: $id}) RETURN entry.head_revision AS head"


class Neo4jCatalogEntryRepositoryAdapter(ICatalogEntryRepository):
    """Catalog entries and their revisions; `Revision.revision_key` guards the head.

    The client opens a separate short transaction only to report the actual head after a
    constraint conflict, because Neo4j ends the failed transaction.
    """

    def __init__(self, transaction: TransactionProvider, client: Neo4jClient) -> None:
        self._transaction: TransactionProvider = transaction
        self._client: Neo4jClient = client

    async def add(self, entry: CatalogEntry) -> None:
        """Stage a new entry with its revision 1.

        Raises:
            ReferenceNotInSpaceError: The space or a source is not in the space.
            CatalogEntryAlreadyExistsError: The kind and name exist in the space.
            EntryAlreadyExistsError: The id is taken.
        """
        transaction: Neo4jTransaction = self._transaction()
        await require_references(
            transaction, space_id=entry.space_id, source_ids=entry.head.source_ids
        )
        try:
            await transaction.run(
                _CREATE,
                {
                    "space_id": entry.space_id.value,
                    "entry": CatalogEntryNodeMapper.to_properties(entry),
                    "revision": CatalogEntryNodeMapper.to_revision_properties(
                        entry.id, entry.name, entry.head
                    ),
                },
            )
        except GraphStoreConstraintViolatedError as error:
            if error.metadata.get("property") == "catalog_key":
                raise CatalogEntryAlreadyExistsError(
                    f"A catalog entry {entry.kind.value}:{entry.name.value} already exists "
                    "in this space.",
                    {"kind": entry.kind.value, "name": entry.name.value},
                    next_steps=[
                        f"Run `noesis catalog revise {entry.kind.value}:{entry.name.value}` "
                        "to change the existing entry."
                    ],
                ) from error
            raise already_exists(error, what="catalog entry", key=entry.id.value) from error
        await self._link_sources(transaction, entry.id, entry.head)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> CatalogEntry | None:
        """The entry with this id in `space_id`, or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _BY_ID, {"id": record_id.value, "space_id": space_id.value}
        )
        return self._entity(rows)

    async def get_by_key(
        self, space_id: SpaceId, kind: CatalogEntryKindEnum, name: str
    ) -> CatalogEntry | None:
        """The entry with this kind and exact name in `space_id`, or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _BY_KEY, {"catalog_key": catalog_key(space_id, kind, name)}
        )
        return self._entity(rows)

    async def get_for_update(
        self, record_id: RecordId, *, space_id: SpaceId
    ) -> CatalogEntry | None:
        """Lock the entry node until the unit of work ends, then read it (A-13)."""
        locked: list[dict[str, Any]] = await self._transaction().run(
            _LOCK, {"id": record_id.value, "space_id": space_id.value}
        )
        if not locked:
            return None
        return await self.get(record_id, space_id=space_id)

    async def append_revision(self, entry: CatalogEntry, revision: CatalogRevision) -> None:
        """Stage `revision` as the new head, moving `head_revision` from n-1 to n.

        Raises:
            RevisionConflictError: The stored head is not n-1, or revision n already exists;
                metadata has the expected and actual head.
        """
        transaction: Neo4jTransaction = self._transaction()
        await require_references(
            transaction, space_id=entry.space_id, source_ids=revision.source_ids
        )
        try:
            appended: list[dict[str, Any]] = await transaction.run(
                _APPEND,
                {
                    "id": entry.id.value,
                    "space_id": entry.space_id.value,
                    "previous": revision.number - 1,
                    "number": revision.number,
                    "updated_at": entry.updated_at,
                    "revision": CatalogEntryNodeMapper.to_revision_properties(
                        entry.id, entry.name, revision
                    ),
                },
            )
        except GraphStoreConstraintViolatedError as error:
            async with await self._client.begin() as reader:
                raise await self._conflict(reader, entry.id, revision) from error
        if not appended:
            raise await self._conflict(transaction, entry.id, revision)
        await self._link_sources(transaction, entry.id, revision)

    @staticmethod
    def _entity(rows: list[dict[str, Any]]) -> CatalogEntry | None:
        if not rows:
            return None
        return CatalogEntryNodeMapper.to_entity(rows[0]["entry"], rows[0]["revisions"])

    @staticmethod
    async def _link_sources(
        transaction: Neo4jTransaction, record_id: RecordId, revision: CatalogRevision
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
        transaction: Neo4jTransaction, record_id: RecordId, revision: CatalogRevision
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
            next_steps=["Run `noesis catalog show`, re-apply the change, retry."],
        )
