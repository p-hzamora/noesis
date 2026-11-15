"""`ICatalogEntryReadRepository` over the catalog nodes: DTOs, scoped to one space."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDetailDto,
    CatalogEntryDto,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    RecordId,
    SpaceId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .mappers import CatalogDtoMapper, catalog_key

_REVISION_OF_ENTRY: LiteralString = (
    "MATCH (revision:Revision {revision_key: entry.id + ':' "
    "+ toString(coalesce($revision, entry.head_revision))})"
)
_RETURN_BOTH: LiteralString = (
    "\nRETURN properties(entry) AS entry, properties(revision) AS revision"
)
_BY_ID: LiteralString = (
    "MATCH (entry:CatalogEntry {id: $id, space_id: $space_id})\n"
    + _REVISION_OF_ENTRY
    + _RETURN_BOTH
)
_BY_KEY: LiteralString = (
    "MATCH (entry:CatalogEntry {catalog_key: $catalog_key})\n" + _REVISION_OF_ENTRY + _RETURN_BOTH
)
_FIND: LiteralString = """
MATCH (entry:CatalogEntry {space_id: $space_id})
WHERE ($kind IS NULL OR entry.entry_kind = $kind)
  AND ($name_prefix IS NULL OR entry.name STARTS WITH $name_prefix)
MATCH (revision:Revision {revision_key: entry.id + ':' + toString(entry.head_revision)})
RETURN properties(entry) AS entry, properties(revision) AS revision
ORDER BY entry.entry_kind, entry.name
"""


class Neo4jCatalogEntryReadRepositoryAdapter(ICatalogEntryReadRepository):
    """Each call reads in its own short transaction; another space's entry reads as None."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def get_by_id(
        self, record_id: RecordId, *, space_id: SpaceId, revision: int | None = None
    ) -> CatalogEntryDetailDto | None:
        """The entry with the requested revision (the head by default), or None."""
        rows: list[dict[str, Any]] = await self._read(
            _BY_ID, id=record_id.value, space_id=space_id.value, revision=revision
        )
        return (
            CatalogDtoMapper.to_detail_dto(rows[0]["entry"], rows[0]["revision"]) if rows else None
        )

    async def get_by_key(
        self,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: str,
        *,
        revision: int | None = None,
    ) -> CatalogEntryDetailDto | None:
        """Like `get_by_id`, found by kind and exact name."""
        rows: list[dict[str, Any]] = await self._read(
            _BY_KEY, catalog_key=catalog_key(space_id, kind, name), revision=revision
        )
        return (
            CatalogDtoMapper.to_detail_dto(rows[0]["entry"], rows[0]["revision"]) if rows else None
        )

    async def find(
        self,
        space_id: SpaceId,
        *,
        kind: CatalogEntryKindEnum | None = None,
        name_prefix: str | None = None,
    ) -> tuple[CatalogEntryDto, ...]:
        """Entries of `space_id`, optionally narrowed by kind and by name prefix."""
        rows: list[dict[str, Any]] = await self._read(
            _FIND,
            space_id=space_id.value,
            kind=kind.value if kind is not None else None,
            name_prefix=name_prefix,
        )
        return tuple(CatalogDtoMapper.to_entry_dto(row["entry"], row["revision"]) for row in rows)

    async def _read(self, query: LiteralString, **parameters: Any) -> list[dict[str, Any]]:
        async with await self._client.begin() as transaction:
            return await transaction.run(query, parameters)
