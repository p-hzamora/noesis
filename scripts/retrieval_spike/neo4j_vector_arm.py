"""Prototype semantic projection, option B: `:IndexChunk` nodes and a Neo4j vector index.

One chunk per record (title and body, as in option A). Embedding runs in a long-lived child
process of Vectra's interpreter (`embed_helper.py`, `-I`), so Noesis's environment gets no torch.
Each Noesis process starts its own helper on first use, which is what an in-process embedder
would cost (interpreter plus torch import plus model load), and keeps it for the process's life.
The cursor is Neo4j's `:IndexCursor` (`semantic`): this arm brings no cursor store of its own.
"""

# ruff: noqa: S101

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
    RankedCandidatesDto,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    IIndexWriter,
    ProjectionEntryDto,
)
from noesis.bounded_context.retrieval.domain.enums import CandidateKindEnum
from noesis.bounded_context.retrieval.domain.value_objects import ProjectionKey
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .vectra_arm import HF_HOME, KIND, document_text

VECTRA_PYTHON: Final[str] = "/home/phzamora/.local/share/uv/tools/vectra/bin/python"
HELPER: Final[Path] = Path(__file__).resolve().parent / "embed_helper.py"
VECTOR_INDEX: Final[str] = "index_chunk_embedding"
OVER_FETCH_FLOOR: Final[int] = 1


class EmbedderProcess:
    """A resident `embed_helper.py` child; starts on first use and reports its own load time."""

    def __init__(self, model_id: str) -> None:
        self._model_id: str = model_id
        self._process: asyncio.subprocess.Process | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self.ready: dict[str, Any] = {}
        self.start_seconds: float = 0.0
        self.encode_ms: list[float] = []

    async def _start(self) -> asyncio.subprocess.Process:
        if self._process is None:
            started = time.perf_counter()
            self._process = await asyncio.create_subprocess_exec(
                VECTRA_PYTHON,
                "-I",
                str(HELPER),
                self._model_id,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin"),
                    "HOME": "/nonexistent",
                    "HF_HOME": HF_HOME,
                },
                cwd="/",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1 << 26,
            )
            assert self._process.stdout is not None
            self.ready = json.loads(await self._process.stdout.readline())
            self.start_seconds = time.perf_counter() - started
        return self._process

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Normalised embeddings of `texts`."""
        async with self._lock:
            process = await self._start()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write((json.dumps({"op": "encode", "texts": texts}) + "\n").encode())
            await process.stdin.drain()
            reply = json.loads(await process.stdout.readline())
        self.encode_ms.append(float(reply["ms"]))
        return reply["vectors"]

    async def token_counts(self, texts: list[str]) -> list[int]:
        """Token counts per text (to see what the model's window truncates)."""
        async with self._lock:
            process = await self._start()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write((json.dumps({"op": "tokens", "texts": texts}) + "\n").encode())
            await process.stdin.drain()
            reply = json.loads(await process.stdout.readline())
        return reply["counts"]

    async def close(self) -> None:
        """Ask the helper to quit and wait for it."""
        if self._process is not None and self._process.returncode is None:
            assert self._process.stdin is not None
            self._process.stdin.write(b'{"op": "quit"}\n')
            await self._process.stdin.drain()
            self._process.stdin.close()
            await self._process.wait()


def _chunk_key(space_id: str, record_id: str) -> str:
    return f"{space_id}:{record_id}:0"


class Neo4jVectorWriter(IIndexWriter):
    """Upserts one `:IndexChunk` per record; `clear` also creates the schema (rebuild path)."""

    def __init__(self, client: Neo4jClient, embedder: EmbedderProcess, dimension: int) -> None:
        self._client: Neo4jClient = client
        self._embedder: EmbedderProcess = embedder
        self._dimension: int = dimension
        self.upsert_seconds: list[float] = []

    @property
    def kind(self) -> str:
        """Projection name."""
        return KIND

    async def ensure_schema(self) -> None:
        """Uniqueness constraint and cosine vector index, each in its own transaction."""
        statements = (
            "CREATE CONSTRAINT index_chunk_key IF NOT EXISTS "
            "FOR (c:IndexChunk) REQUIRE c.chunk_key IS UNIQUE",
            f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (c:IndexChunk) ON c.embedding "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {self._dimension}, "
            "`vector.similarity_function`: 'cosine'}}",
        )
        for statement in statements:
            async with await self._client.begin() as transaction:
                await transaction.run(statement)  # type: ignore[arg-type]
                await transaction.commit()
        async with await self._client.begin() as transaction:
            await transaction.run("CALL db.awaitIndexes(120)")

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Embed title and body and MERGE the record's chunk (any older revision is replaced)."""
        started = time.perf_counter()
        text = document_text(entry.record.title, entry.record.body)
        (vector,) = await self._embedder.encode([text])
        async with await self._client.begin() as transaction:
            await transaction.run(
                "MERGE (c:IndexChunk {chunk_key: $chunk_key}) "
                "SET c.space_id = $space_id, c.record_id = $record_id, c.revision = $revision, "
                "c.ordinal = 0 "
                "WITH c CALL db.create.setNodeVectorProperty(c, 'embedding', $vector)",
                {
                    "chunk_key": _chunk_key(entry.space_id, entry.key.record_id),
                    "space_id": entry.space_id,
                    "record_id": entry.key.record_id,
                    "revision": entry.key.revision,
                    "vector": vector,
                },
            )
            await transaction.commit()
        self.upsert_seconds.append(time.perf_counter() - started)

    async def clear(self, space_id: str) -> None:
        """Create the schema if missing, then delete every chunk of the space."""
        await self.ensure_schema()
        async with await self._client.begin() as transaction:
            await transaction.run(
                "MATCH (c:IndexChunk {space_id: $space_id}) DETACH DELETE c",
                {"space_id": space_id},
            )
            await transaction.commit()

    def profile(self) -> dict[str, JsonValue]:
        """Model, dimension and similarity the index was built with."""
        return {
            "store": "neo4j-vector-index",
            "model_id": self._embedder._model_id,  # one spike module
            "dimension": self._dimension,
            "similarity": "cosine",
        }

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """Record id to the revision held."""
        async with await self._client.begin() as transaction:
            rows = await transaction.run(
                "MATCH (c:IndexChunk {space_id: $space_id}) "
                "RETURN c.record_id AS record_id, c.revision AS revision",
                {"space_id": space_id},
            )
        return {row["record_id"]: row["revision"] for row in rows}


class Neo4jVectorSource(ICandidateSource):
    """Embeds the query and calls `db.index.vector.queryNodes` (no pre-filter on this tag)."""

    def __init__(self, client: Neo4jClient, embedder: EmbedderProcess, dimension: int) -> None:
        self._client: Neo4jClient = client
        self._embedder: EmbedderProcess = embedder
        self._dimension: int = dimension
        self.query_seconds: list[float] = []

    @property
    def kind(self) -> CandidateKindEnum:
        """Always `semantic`."""
        return CandidateKindEnum.SEMANTIC

    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """Up to `limit` chunks of the space, best first."""
        try:
            (vector,) = await self._embedder.encode([text])
            started = time.perf_counter()
            async with await self._client.begin() as transaction:
                rows = await transaction.run(
                    f"CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $vector) "
                    "YIELD node, score WHERE node.space_id = $space_id "
                    "RETURN node.record_id AS record_id, node.revision AS revision "
                    "ORDER BY score DESC LIMIT $limit",
                    {"k": limit, "vector": vector, "space_id": space_id, "limit": limit},
                )
            self.query_seconds.append(time.perf_counter() - started)
        except Exception as error:
            raise CandidateSourceUnavailableError(str(error)) from error
        return RankedCandidatesDto(
            hits=tuple(
                ProjectionKey(record_id=row["record_id"], revision=row["revision"]) for row in rows
            )
        )

    def profile(self) -> dict[str, JsonValue]:
        """Same as the writer's."""
        return {
            "store": "neo4j-vector-index",
            "model_id": self._embedder._model_id,
            "dimension": self._dimension,
            "similarity": "cosine",
        }


@dataclass(slots=True)
class Neo4jVectorKit:
    """The pieces of one process's arm B, so the harness can close and inspect them."""

    embedder: EmbedderProcess
    writer: Neo4jVectorWriter
    source: Neo4jVectorSource
    extras: dict[str, Any] = field(default_factory=dict)
