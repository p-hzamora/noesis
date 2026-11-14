"""`ISourceRepository` over `:Record:Source` nodes linked `IN_SPACE`."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Source
from noesis.bounded_context.knowledge.domain.repositories import ISourceRepository
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    RecordId,
    SourceKindEnum,
    SpaceId,
)

from .mappers import SourceNodeMapper, source_key
from .neo4j_write_support import TransactionProvider, create_unique, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
CREATE (source:Record:Source $source)-[:IN_SPACE]->(space)
"""
_BY_ID: LiteralString = """
MATCH (source:Source {id: $id, space_id: $space_id})
RETURN properties(source) AS source
"""
_BY_NATURAL_KEY: LiteralString = """
MATCH (source:Source {source_key: $source_key})
RETURN properties(source) AS source
"""


class Neo4jSourceRepositoryAdapter(ISourceRepository):
    """Sources are unique by id and by the hash of their natural key (`Source.source_key`)."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def add(self, source: Source) -> None:
        """Stage a new source.

        Raises:
            ReferenceNotInSpaceError: The space does not exist.
            EntryAlreadyExistsError: The id or the natural key is taken.
        """
        await require_references(self._transaction(), space_id=source.space_id)
        await create_unique(
            self._transaction(),
            _CREATE,
            {"space_id": source.space_id.value, "source": SourceNodeMapper.to_properties(source)},
            what="source",
            key=source.locator,
        )

    async def get(self, source_id: RecordId, *, space_id: SpaceId) -> Source | None:
        """The source with this id in `space_id`, or None."""
        return await self._one(_BY_ID, {"id": source_id.value, "space_id": space_id.value})

    async def get_by_natural_key(
        self,
        *,
        space_id: SpaceId,
        kind: SourceKindEnum,
        locator: str,
        digest: ContentHash | None,
    ) -> Source | None:
        """The source with this natural key, or None."""
        natural: str = source_key(space_id=space_id, kind=kind, locator=locator, digest=digest)
        return await self._one(_BY_NATURAL_KEY, {"source_key": natural})

    async def _one(self, query: LiteralString, parameters: dict[str, Any]) -> Source | None:
        rows: list[dict[str, Any]] = await self._transaction().run(query, parameters)
        return SourceNodeMapper.to_entity(rows[0]["source"]) if rows else None
