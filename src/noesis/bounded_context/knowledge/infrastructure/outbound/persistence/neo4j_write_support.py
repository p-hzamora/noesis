"""What every Knowledge Neo4j adapter shares: the open transaction, races and reference checks.

The shared client already turned driver exceptions into `GraphStore*Error`; here a lost
uniqueness race becomes Knowledge's `EntryAlreadyExistsError`, which handlers resolve by
re-reading the winner.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.exceptions import (
    EntryAlreadyExistsError,
    GraphStoreConstraintViolatedError,
    ReferenceNotInSpaceError,
)
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jTransaction

type TransactionProvider = Callable[[], Neo4jTransaction]
"""The unit of work's open transaction; repositories never open their own."""

_REFERENCES: LiteralString = """
OPTIONAL MATCH (space:Space {id: $space_id})
OPTIONAL MATCH (project:Project {id: $project_id, space_id: $space_id})
WITH space, project
OPTIONAL MATCH (source:Source {space_id: $space_id})
WHERE source.id IN $source_ids
RETURN space IS NOT NULL AS space_found,
       project IS NOT NULL AS project_found,
       collect(source.id) AS found_source_ids
"""


def already_exists(
    error: GraphStoreConstraintViolatedError, *, what: str, key: str
) -> EntryAlreadyExistsError:
    """The Knowledge error for a write that lost a uniqueness race."""
    metadata: dict[str, JsonValue] = {"kind": what, "key": key}
    for name in ("label", "property"):
        if name in error.metadata:
            metadata[name] = error.metadata[name]
    return EntryAlreadyExistsError(f"{what.capitalize()} {key} already exists.", metadata)


async def create_unique(
    transaction: Neo4jTransaction,
    query: LiteralString,
    parameters: Mapping[str, Any],
    *,
    what: str,
    key: str,
) -> list[dict[str, Any]]:
    """Run a creating statement; a uniqueness violation means another writer got there first.

    Raises:
        EntryAlreadyExistsError: A uniqueness constraint rejected the write.
    """
    try:
        return await transaction.run(query, parameters)
    except GraphStoreConstraintViolatedError as error:
        raise already_exists(error, what=what, key=key) from error


async def require_references(
    transaction: Neo4jTransaction,
    *,
    space_id: SpaceId,
    project_id: RecordId | None = None,
    source_ids: Sequence[RecordId] = (),
) -> None:
    """Fail unless the space exists and every referenced project and source is in it (D-006).

    Raises:
        ReferenceNotInSpaceError: Names what is missing; nothing has been written.
    """
    rows: list[dict[str, Any]] = await transaction.run(
        _REFERENCES,
        {
            "space_id": space_id.value,
            "project_id": project_id.value if project_id else None,
            "source_ids": [source_id.value for source_id in source_ids],
        },
    )
    row: dict[str, Any] = rows[0]
    missing: dict[str, JsonValue] = {}
    if not row["space_found"]:
        missing["space_id"] = space_id.value
    if project_id is not None and not row["project_found"]:
        missing["project_id"] = project_id.value
    absent: list[JsonValue] = [
        source_id.value
        for source_id in source_ids
        if source_id.value not in row["found_source_ids"]
    ]
    if absent:
        missing["source_ids"] = absent
    if missing:
        raise ReferenceNotInSpaceError(
            f"A referenced space, project or source does not exist in space {space_id.value}.",
            {"space_id": space_id.value, **missing},
            next_steps=["Check the ids and the active space."],
        )
