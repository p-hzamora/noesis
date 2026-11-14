"""`IExperienceRepository` over write-once `:Record:Experience` nodes."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities import Experience
from noesis.bounded_context.knowledge.domain.repositories import IExperienceRepository
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jTransaction

from .mappers import ExperienceNodeMapper
from .neo4j_write_support import TransactionProvider, create_unique, require_references

_CREATE: LiteralString = """
MATCH (space:Space {id: $space_id})
CREATE (experience:Record:Experience $experience)-[:IN_SPACE]->(space)
"""
_LINK_PROJECT: LiteralString = """
MATCH (experience:Experience {id: $id}), (project:Project {id: $project_id})
CREATE (experience)-[:BELONGS_TO_PROJECT]->(project)
"""
_LINK_SOURCES: LiteralString = """
MATCH (experience:Experience {id: $id})
UNWIND $source_ids AS source_id
MATCH (source:Source {id: source_id})
CREATE (experience)-[:FROM_SOURCE]->(source)
"""
_LOAD: LiteralString = """
MATCH (experience:Experience {id: $id, space_id: $space_id})
RETURN properties(experience) AS experience
"""


class Neo4jExperienceRepositoryAdapter(IExperienceRepository):
    """Experiences: created once, linked to their space, project and sources, never changed."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def add(self, experience: Experience) -> None:
        """Stage a new experience.

        Raises:
            ReferenceNotInSpaceError: The space, project or a source is not in the space.
            EntryAlreadyExistsError: The id is taken.
        """
        transaction: Neo4jTransaction = self._transaction()
        await require_references(
            transaction,
            space_id=experience.space_id,
            project_id=experience.project_id,
            source_ids=experience.source_ids,
        )
        await create_unique(
            transaction,
            _CREATE,
            {
                "space_id": experience.space_id.value,
                "experience": ExperienceNodeMapper.to_properties(experience),
            },
            what="experience",
            key=experience.id.value,
        )
        if experience.project_id is not None:
            await transaction.run(
                _LINK_PROJECT,
                {"id": experience.id.value, "project_id": experience.project_id.value},
            )
        await transaction.run(
            _LINK_SOURCES,
            {
                "id": experience.id.value,
                "source_ids": [source_id.value for source_id in experience.source_ids],
            },
        )

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Experience | None:
        """The experience with this id in `space_id`, or None."""
        rows: list[dict[str, Any]] = await self._transaction().run(
            _LOAD, {"id": record_id.value, "space_id": space_id.value}
        )
        return ExperienceNodeMapper.to_entity(rows[0]["experience"]) if rows else None
