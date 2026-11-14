"""`IStoreSchema` over Neo4j: named, additive schema steps recorded on `:StoreMeta` (A-3, D-027).

Neo4j does not allow schema changes and data writes in one transaction, so a step's statements
commit first and the record on `:StoreMeta` second. Every statement is idempotent
(`IF NOT EXISTS`), so a crash between the two is repaired by the next `store init`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, LiteralString

from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.schema_steps import CORE_STEP
from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

STORE_META_NAME: Final[str] = "noesis"


@dataclass(frozen=True, slots=True)
class Neo4jSchemaStep:
    """One named step: idempotent schema statements (constraints, indexes).

    Attributes:
        name: Stable name recorded once applied (`core`, ...).
        statements: Cypher schema statements, each idempotent (`IF NOT EXISTS`).
    """

    name: str
    statements: tuple[LiteralString, ...]


CORE_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=CORE_STEP,
    statements=(
        "CREATE CONSTRAINT record_id IF NOT EXISTS FOR (n:Record) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT space_id IF NOT EXISTS FOR (n:Space) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT space_key IF NOT EXISTS FOR (n:Space) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT revision_key IF NOT EXISTS FOR (n:Revision) REQUIRE n.revision_key IS UNIQUE",
        "CREATE CONSTRAINT project_key IF NOT EXISTS FOR (n:Project) REQUIRE n.project_key IS UNIQUE",
        "CREATE CONSTRAINT source_key IF NOT EXISTS FOR (n:Source) REQUIRE n.source_key IS UNIQUE",
        "CREATE CONSTRAINT idempotency_key IF NOT EXISTS FOR (n:IdempotencyKey) REQUIRE n.key IS UNIQUE",
    ),
)
"""Knowledge's own step. `CatalogEntry.catalog_key` is reserved and registered by C6."""

_APPLIED: LiteralString = """
OPTIONAL MATCH (meta:StoreMeta {name: $name})
RETURN coalesce(meta.applied_steps, []) AS steps
"""
_RECORD: LiteralString = """
MERGE (meta:StoreMeta {name: $name})
ON CREATE SET meta.applied_steps = [], meta.created_at = datetime()
WITH meta
WHERE NOT $step IN meta.applied_steps
SET meta.applied_steps = meta.applied_steps + $step, meta.updated_at = datetime()
RETURN meta.name AS name
"""


class Neo4jStoreSchemaAdapter(IStoreSchema):
    """The registry of schema steps and their application.

    Raises (at construction):
        InvalidConfigurationError: Two registered steps share a name.
    """

    def __init__(self, client: Neo4jClient, steps: Sequence[Neo4jSchemaStep]) -> None:
        names: list[str] = [step.name for step in steps]
        duplicates: list[str] = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise InvalidConfigurationError(
                f"Schema step(s) registered twice: {', '.join(duplicates)}.",
                {"duplicate_steps": [*duplicates]},
                next_steps=["Give every registered schema step a unique name."],
            )
        self._client: Neo4jClient = client
        self._steps: dict[str, Neo4jSchemaStep] = {step.name: step for step in steps}

    def registered_steps(self) -> tuple[str, ...]:
        """Names of every registered step, in registration order."""
        return tuple(self._steps)

    async def applied_steps(self) -> frozenset[str]:
        """Steps recorded on `:StoreMeta`; empty on an uninitialised store."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_APPLIED, {"name": STORE_META_NAME})
        return frozenset(rows[0]["steps"])

    async def apply_step(self, name: str) -> bool:
        """Apply a registered step unless it is recorded as applied.

        Returns:
            True when this call recorded it, False when it was already recorded.

        Raises:
            InvalidConfigurationError: No step has this name.
        """
        step: Neo4jSchemaStep | None = self._steps.get(name)
        if step is None:
            raise InvalidConfigurationError(
                f"No schema step named {name!r} is registered.",
                {"step": name, "registered_steps": [*self._steps]},
            )
        if name in await self.applied_steps():
            return False
        async with await self._client.begin() as schema:
            for statement in step.statements:
                await schema.run(statement)
            await schema.commit()
        async with await self._client.begin() as meta:
            recorded: list[dict[str, Any]] = await meta.run(
                _RECORD, {"name": STORE_META_NAME, "step": name}
            )
            await meta.commit()
        return bool(recorded)
