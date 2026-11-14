"""`IKnowledgeSpaceRepository` over `:Space` nodes."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.repositories import IKnowledgeSpaceRepository
from noesis.bounded_context.knowledge.domain.value_objects import Key, SpaceId

from .mappers import SpaceNodeMapper
from .neo4j_write_support import TransactionProvider, create_unique

_CREATE: LiteralString = "CREATE (space:Space $space)"
_BY_ID: LiteralString = "MATCH (space:Space {id: $id}) RETURN properties(space) AS space"
_BY_KEY: LiteralString = "MATCH (space:Space {key: $key}) RETURN properties(space) AS space"


class Neo4jKnowledgeSpaceRepositoryAdapter(IKnowledgeSpaceRepository):
    """Spaces are unique by id and by key (`Space.id`, `Space.key` constraints)."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def add(self, space: KnowledgeSpace) -> None:
        """Stage a new space.

        Raises:
            EntryAlreadyExistsError: The id or key is taken.
        """
        await create_unique(
            self._transaction(),
            _CREATE,
            {"space": SpaceNodeMapper.to_properties(space)},
            what="space",
            key=space.key.value,
        )

    async def get(self, space_id: SpaceId) -> KnowledgeSpace | None:
        """The space with this id, or None."""
        return await self._one(_BY_ID, {"id": space_id.value})

    async def get_by_key(self, key: Key) -> KnowledgeSpace | None:
        """The space with this key, or None."""
        return await self._one(_BY_KEY, {"key": key.value})

    async def _one(self, query: LiteralString, parameters: dict[str, Any]) -> KnowledgeSpace | None:
        rows: list[dict[str, Any]] = await self._transaction().run(query, parameters)
        return SpaceNodeMapper.to_entity(rows[0]["space"]) if rows else None
