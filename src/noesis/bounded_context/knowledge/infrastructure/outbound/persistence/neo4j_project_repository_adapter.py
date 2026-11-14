"""`IProjectRepository` over `:Record:Project` nodes linked `IN_SPACE`."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Project
from noesis.bounded_context.knowledge.domain.repositories import IProjectRepository
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId

from .mappers import ProjectNodeMapper, project_key
from .neo4j_write_support import TransactionProvider, create_unique, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
CREATE (project:Record:Project $project)-[:IN_SPACE]->(space)
"""
_BY_ID: LiteralString = """
MATCH (project:Project {id: $id, space_id: $space_id})
RETURN properties(project) AS project
"""
_BY_KEY: LiteralString = """
MATCH (project:Project {project_key: $project_key})
RETURN properties(project) AS project
"""


class Neo4jProjectRepositoryAdapter(IProjectRepository):
    """Projects are unique by id and by `<space>:<key>` (`Project.project_key`)."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def add(self, project: Project) -> None:
        """Stage a new project.

        Raises:
            ReferenceNotInSpaceError: The space does not exist.
            EntryAlreadyExistsError: The id is taken, or the key is taken in the space.
        """
        await require_references(self._transaction(), space_id=project.space_id)
        await create_unique(
            self._transaction(),
            _CREATE,
            {
                "space_id": project.space_id.value,
                "project": ProjectNodeMapper.to_properties(project),
            },
            what="project",
            key=project.key.value,
        )

    async def get(self, project_id: RecordId, *, space_id: SpaceId) -> Project | None:
        """The project with this id in `space_id`, or None."""
        return await self._one(_BY_ID, {"id": project_id.value, "space_id": space_id.value})

    async def get_by_key(self, key: Key, *, space_id: SpaceId) -> Project | None:
        """The project with this key in `space_id`, or None."""
        return await self._one(_BY_KEY, {"project_key": project_key(space_id, key)})

    async def _one(self, query: LiteralString, parameters: dict[str, Any]) -> Project | None:
        rows: list[dict[str, Any]] = await self._transaction().run(query, parameters)
        return ProjectNodeMapper.to_entity(rows[0]["project"]) if rows else None
