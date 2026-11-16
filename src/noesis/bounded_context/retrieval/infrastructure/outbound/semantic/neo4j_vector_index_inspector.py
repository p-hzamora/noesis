"""Reads the state and options of the semantic vector index (never creates or drops it)."""

import asyncio
import time
from typing import Any, LiteralString

from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient
from noesis.utils import FrozenObject

from .semantic_graph_contracts import VECTOR_INDEX_NAME

ONLINE: str = "ONLINE"
EXPECTED_DIMENSIONS: int = 384
EXPECTED_SIMILARITY: str = "COSINE"
ONLINE_WAIT_SECONDS: float = 60.0
ONLINE_POLL_SECONDS: float = 0.5

_SHOW: LiteralString = """
SHOW VECTOR INDEXES
YIELD name, state, options, labelsOrTypes, properties
WHERE name = $name
RETURN state, options, labelsOrTypes AS labels, properties
"""


class VectorIndexStateDto(FrozenObject):
    """What `SHOW VECTOR INDEXES` reports for the semantic index.

    Attributes:
        exists: Whether the index exists.
        state: `ONLINE`, `POPULATING`, `FAILED`, ...; null when it does not exist.
        dimensions: Configured vector size.
        similarity: Configured similarity function, upper case.
        provider: Index provider.
        compatible: Exists over `:Embedding(vector)` with 384 dimensions and cosine.
    """

    exists: bool
    state: str | None = None
    dimensions: int | None = None
    similarity: str | None = None
    provider: str | None = None
    compatible: bool = False

    @property
    def queryable(self) -> bool:
        """Compatible and online."""
        return self.compatible and self.state == ONLINE

    def as_json(self) -> dict[str, JsonValue]:
        """Plain JSON for diagnostics."""
        return dict(self.model_dump(mode="json"))


class Neo4jVectorIndexInspector:
    """Inspects `retrieval_semantic_vector`.

    Args:
        client: The shared Neo4j client.
        name: The index name.
    """

    def __init__(self, client: Neo4jClient, name: str = VECTOR_INDEX_NAME) -> None:
        self._client: Neo4jClient = client
        self._name: str = name

    async def state(self) -> VectorIndexStateDto:
        """The index's current state and options."""
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_SHOW, {"name": self._name})
        if not rows:
            return VectorIndexStateDto(exists=False)
        row: dict[str, Any] = rows[0]
        options: dict[str, Any] = row["options"] or {}
        config: dict[str, Any] = options.get("indexConfig") or {}
        dimensions: Any = config.get("vector.dimensions")
        similarity: Any = config.get("vector.similarity_function")
        return VectorIndexStateDto(
            exists=True,
            state=row["state"],
            dimensions=int(dimensions) if dimensions is not None else None,
            similarity=str(similarity).upper() if similarity is not None else None,
            provider=options.get("indexProvider"),
            compatible=(
                row["labels"] == ["Embedding"]
                and row["properties"] == ["vector"]
                and dimensions is not None
                and int(dimensions) == EXPECTED_DIMENSIONS
                and str(similarity).upper() == EXPECTED_SIMILARITY
            ),
        )

    async def wait_online(
        self, timeout_seconds: float = ONLINE_WAIT_SECONDS
    ) -> VectorIndexStateDto:
        """Poll until the index is online, failed, incompatible or the timeout passes."""
        deadline: float = time.monotonic() + timeout_seconds
        while True:
            found: VectorIndexStateDto = await self.state()
            if (
                not found.exists
                or not found.compatible
                or found.state in {ONLINE, "FAILED"}
                or time.monotonic() >= deadline
            ):
                return found
            await asyncio.sleep(ONLINE_POLL_SECONDS)


async def check_semantic_vector_index(client: Neo4jClient) -> None:
    """The `retrieval_semantic` step's check: the index exists with 384 dimensions and cosine.

    Waits up to 60 s for it to come online. An index with other options is never dropped
    automatically: the step stays unrecorded and the error says how to repair it.

    Raises:
        InvalidConfigurationError: Missing, incompatible or failed.
    """
    found: VectorIndexStateDto = await Neo4jVectorIndexInspector(client).wait_online()
    if found.exists and found.compatible and found.state != "FAILED":
        return  # ONLINE, or still POPULATING after the wait: searches report it unavailable
    raise InvalidConfigurationError(
        f"The vector index {VECTOR_INDEX_NAME} is "
        f"{'missing' if not found.exists else found.state if found.compatible else 'incompatible'}.",
        {"index": VECTOR_INDEX_NAME, **found.as_json()},
        next_steps=[
            f"Drop the index yourself (`DROP INDEX {VECTOR_INDEX_NAME}`), run `noesis store init`,"
            " then `noesis index rebuild --yes`.",
        ],
    )
