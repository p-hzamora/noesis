"""The semantic `ICandidateSource`: global ANN over chunk vectors, filtered, one rank per record.

`db.index.vector.queryNodes` (Neo4j 5.26 Community) returns the nearest chunks of every space;
chunks of another space or profile are dropped here and never leave the adapter. Records rank
by their best chunk's cosine (ties by record id, then revision), so a long record gets one
contribution. When filtering and chunk dedup leave fewer than `limit` records, `k` doubles up
to 2,000 or the number of chunk nodes. A sparse space can still be starved by global ANN; the
caller's admission reports `filter_shortfall`.
"""

from typing import Any, LiteralString

from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from ....application.ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
    RankedCandidatesDto,
)
from ....application.ports.embedding import (
    MAX_QUERY_CHARACTERS,
    EmbedderUnavailableError,
    ITextEmbedder,
)
from ....domain.enums import CandidateKindEnum
from ....domain.value_objects import ProjectionKey
from .neo4j_vector_index_inspector import Neo4jVectorIndexInspector, VectorIndexStateDto
from .semantic_graph_contracts import VECTOR_INDEX_NAME

FIRST_K_FACTOR: int = 4
MAX_K: int = 2_000
MAX_ATTEMPTS: int = 6

_QUERY: LiteralString = """
CALL db.index.vector.queryNodes($index_name, $k, $vector) YIELD node, score
WHERE node.space_id = $space_id AND node.profile_hash = $profile_hash
RETURN node.record_id AS record_id, node.revision AS revision, score
"""

_COUNT: LiteralString = "MATCH (e:Embedding) RETURN count(e) AS total"


class Neo4jSemanticCandidateSource(ICandidateSource):
    """Answers `find` from `retrieval_semantic_vector`.

    The query vector of one text is kept for the life of this object (one CLI invocation), so the
    searcher's over-fetch retry does not embed twice; nothing is persisted.

    Args:
        client: The shared Neo4j client.
        embedder: Embeds the query with the configured profile.
        inspector: Checks the vector index is online and compatible before querying.
    """

    def __init__(
        self,
        client: Neo4jClient,
        embedder: ITextEmbedder,
        inspector: Neo4jVectorIndexInspector,
    ) -> None:
        self._client: Neo4jClient = client
        self._embedder: ITextEmbedder = embedder
        self._inspector: Neo4jVectorIndexInspector = inspector
        self._vectors: dict[str, tuple[float, ...]] = {}
        self.last_attempts: list[int] = []

    @property
    def kind(self) -> CandidateKindEnum:
        """Always `semantic`."""
        return CandidateKindEnum.SEMANTIC

    def profile(self) -> dict[str, JsonValue]:
        """The configured profile; the built one is compared by the searcher from the manifest."""
        return self._embedder.profile().as_json()

    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """Up to `limit` distinct records of `space_id`, best chunk first.

        Raises:
            CandidateSourceUnavailableError: The query is too long, the embedder cannot answer,
                or the vector index is missing, not online or incompatible. Store outages are
                not caught: they propagate as typed store errors.
        """
        if len(text) > MAX_QUERY_CHARACTERS:
            raise CandidateSourceUnavailableError(
                f"semantic search accepts at most {MAX_QUERY_CHARACTERS} characters"
            )
        index: VectorIndexStateDto = await self._inspector.state()
        if not index.queryable:
            raise CandidateSourceUnavailableError(
                f"the semantic vector index is {index.state or 'missing'}"
                f"{'' if index.compatible or not index.exists else ' and incompatible'}"
            )
        vector: tuple[float, ...] = await self._query_vector(text)
        profile_hash: str = self._embedder.profile().fingerprint()
        best: dict[str, tuple[float, int | None]] = {}
        k: int = min(FIRST_K_FACTOR * limit, MAX_K)
        total: int | None = None
        self.last_attempts = []
        for _ in range(MAX_ATTEMPTS):
            self.last_attempts.append(k)
            best = await self._best_by_record(vector, k, space_id, profile_hash)
            if len(best) >= limit or k >= MAX_K:
                break
            if total is None:
                total = await self._chunk_total()
            if k >= total:
                break
            k = min(2 * k, MAX_K, max(total, k + 1))
        ranked: list[tuple[str, tuple[float, int | None]]] = sorted(
            best.items(),
            key=lambda item: (-item[1][0], item[0], item[1][1] if item[1][1] is not None else -1),
        )
        return RankedCandidatesDto(
            hits=tuple(
                ProjectionKey(record_id=record_id, revision=revision)
                for record_id, (_, revision) in ranked[:limit]
            )
        )

    async def _query_vector(self, text: str) -> tuple[float, ...]:
        cached: tuple[float, ...] | None = self._vectors.get(text)
        if cached is not None:
            return cached
        try:
            vector: tuple[float, ...] = await self._embedder.embed_query(text)
        except EmbedderUnavailableError as error:
            raise CandidateSourceUnavailableError(str(error)) from error
        self._vectors[text] = vector
        return vector

    async def _best_by_record(
        self, vector: tuple[float, ...], k: int, space_id: str, profile_hash: str
    ) -> dict[str, tuple[float, int | None]]:
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _QUERY,
                {
                    "index_name": VECTOR_INDEX_NAME,
                    "k": k,
                    "vector": list(vector),
                    "space_id": space_id,
                    "profile_hash": profile_hash,
                },
            )
        best: dict[str, tuple[float, int | None]] = {}
        for row in rows:
            score: float = float(row["score"])
            held: tuple[float, int | None] | None = best.get(row["record_id"])
            if held is None or score > held[0]:
                best[row["record_id"]] = (score, row["revision"])
        return best

    async def _chunk_total(self) -> int:
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_COUNT)
        return int(rows[0]["total"])
