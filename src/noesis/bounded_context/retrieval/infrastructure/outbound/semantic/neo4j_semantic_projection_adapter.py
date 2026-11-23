"""The `semantic` projection: record text windows embedded into `:Embedding` chunk nodes.

Embeddings are computed in `prepare`, with no transaction open. `commit` replaces every chunk
of the space and record in one short transaction fenced on the writer's lease, so a shorter or
revised text leaves no old chunk behind and a stale lease holder writes nothing. Embeddings of
retracted or superseded heads are kept: admission always reads live Knowledge state.
"""

from collections.abc import Sequence
from typing import Any, LiteralString

from noesis.exceptions import SemanticIndexUnavailableError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction
from noesis.utils import FrozenObject

from ....application.ports.embedding import (
    EmbeddedChunkDto,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
    ITextEmbedder,
)
from ....application.ports.indexing.i_index_writer import ProjectionEntryDto
from ....application.ports.indexing.i_staged_index_writer import IStagedIndexWriter
from ..persistence.neo4j_index_cursor_store_adapter import Neo4jIndexCursorStoreAdapter
from .semantic_graph_contracts import (
    SEMANTIC_KIND,
    content_hash,
    embedding_key,
    passage_text,
    revision_key,
)

INCONSISTENT_REVISION: int = -1
"""What `entries` reports for a record whose chunk set is inconsistent, so `--verify` lists it."""

_EXISTING: LiteralString = """
MATCH (e:Embedding {space_id: $space_id, record_id: $record_id})
RETURN e.revision_key AS revision_key, e.profile_hash AS profile_hash,
       e.content_hash AS content_hash, e.chunk_index AS chunk_index,
       e.chunk_count AS chunk_count
"""

_DELETE_RECORD: LiteralString = """
MATCH (e:Embedding {space_id: $space_id, record_id: $record_id})
DELETE e
"""

_CREATE_CHUNKS: LiteralString = """
UNWIND $chunks AS chunk
CREATE (e:Embedding {
    embedding_key: chunk.key,
    space_id: $space_id,
    record_id: $record_id,
    record_type: $record_type,
    revision_key: $revision_key,
    profile_hash: $profile_hash,
    chunk_index: chunk.index,
    chunk_count: $chunk_count,
    token_start: chunk.token_start,
    token_end: chunk.token_end,
    content_hash: $content_hash
})
SET e.revision = $revision, e.vector = chunk.vector
"""

_CLEAR: LiteralString = "MATCH (e:Embedding {space_id: $space_id}) DELETE e"

_ENTRIES: LiteralString = """
MATCH (e:Embedding {space_id: $space_id})
RETURN e.record_id AS record_id,
       collect(DISTINCT e.revision_key) AS revision_keys,
       collect(DISTINCT e.revision) AS revisions,
       collect(DISTINCT e.profile_hash) AS profiles,
       collect(DISTINCT e.chunk_count) AS counts,
       collect(e.chunk_index) AS indexes
"""


class SemanticPreparedEntryDto(FrozenObject):
    """An entry with its embeddings, ready to commit.

    Attributes:
        entry: The record at its head revision.
        profile_hash: Fingerprint of the profile the chunks were embedded with.
        content_hash: Digest of the embedded text.
        unchanged: The stored chunks already hold this revision, profile and text.
        chunks: The embedded windows; empty for an empty text or an unchanged entry.
    """

    entry: ProjectionEntryDto
    profile_hash: str
    content_hash: str
    unchanged: bool
    chunks: tuple[EmbeddedChunkDto, ...] = ()


class Neo4jSemanticProjectionAdapter(IStagedIndexWriter[SemanticPreparedEntryDto]):
    """`IIndexWriter` of kind `semantic` over `:Embedding` nodes.

    Args:
        client: The shared Neo4j client.
        embedder: Embeds passages with the configured profile.
        cursors: The cursor store whose lease fences every write.
    """

    def __init__(
        self,
        client: Neo4jClient,
        embedder: ITextEmbedder,
        cursors: Neo4jIndexCursorStoreAdapter,
    ) -> None:
        self._client: Neo4jClient = client
        self._embedder: ITextEmbedder = embedder
        self._cursors: Neo4jIndexCursorStoreAdapter = cursors

    @property
    def kind(self) -> str:
        """Always `semantic`."""
        return SEMANTIC_KIND

    def profile(self) -> dict[str, JsonValue]:
        """The configured embedding profile (the built one lives in the cursor's manifest)."""
        return self._embedder.profile().as_json()

    async def prepare(self, entry: ProjectionEntryDto) -> SemanticPreparedEntryDto:
        """Embed the record's windows unless its stored chunks are already current.

        Raises:
            SemanticIndexUnavailableError: The embedder cannot answer; nothing was written.
        """
        text: str = passage_text(entry.record)
        digest: str = content_hash(text)
        profile_hash: str = self._embedder.profile().fingerprint()
        if await self._is_current(entry, profile_hash=profile_hash, digest=digest):
            return SemanticPreparedEntryDto(
                entry=entry, profile_hash=profile_hash, content_hash=digest, unchanged=True
            )
        try:
            passages: list[EmbeddedPassageDto] = await self._embedder.embed_passages([text])
        except EmbedderUnavailableError as error:
            raise SemanticIndexUnavailableError(
                f"The embedder could not embed record {entry.key.record_id}: {error}",
                {"record_id": entry.key.record_id, "reason": str(error)},
                next_steps=[
                    "Start the embedder with `noesis index embedder serve`, or prepare the model"
                    " with `noesis index model prepare`.",
                    "Then rerun `noesis index sync`.",
                ],
            ) from error
        return SemanticPreparedEntryDto(
            entry=entry,
            profile_hash=profile_hash,
            content_hash=digest,
            unchanged=False,
            chunks=passages[0].chunks,
        )

    def entry_of(self, prepared: SemanticPreparedEntryDto) -> ProjectionEntryDto:
        """The entry `prepared` came from."""
        return prepared.entry

    async def commit(self, prepared: SemanticPreparedEntryDto, *, owner: str) -> None:
        """Replace the record's chunks in one transaction fenced on `owner`'s lease."""
        if prepared.unchanged:
            return
        async with await self._client.begin() as transaction:
            await self._cursors.fence(transaction, SEMANTIC_KIND, prepared.entry.space_id, owner)
            await self._replace(transaction, prepared)
            await transaction.commit()

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Prepare and write without a lease (only for callers that hold no lease)."""
        prepared: SemanticPreparedEntryDto = await self.prepare(entry)
        if prepared.unchanged:
            return
        async with await self._client.begin() as transaction:
            await self._replace(transaction, prepared)
            await transaction.commit()

    async def clear(self, space_id: str) -> None:
        """Delete every chunk of the space."""
        async with await self._client.begin() as transaction:
            await transaction.run(_CLEAR, {"space_id": space_id})
            await transaction.commit()

    async def clear_fenced(self, space_id: str, *, owner: str) -> None:
        """Delete every chunk of the space while `owner` holds the lease; other spaces stay."""
        async with await self._client.begin() as transaction:
            await self._cursors.fence(transaction, SEMANTIC_KIND, space_id, owner)
            await transaction.run(_CLEAR, {"space_id": space_id})
            await transaction.commit()

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """Record id to the revision held; `INCONSISTENT_REVISION` for a broken chunk set.

        A chunk set is inconsistent when it mixes revisions or profiles, holds a profile other
        than the configured one, or its chunk indexes are not exactly `0..chunk_count-1`.
        """
        profile_hash: str = self._embedder.profile().fingerprint()
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_ENTRIES, {"space_id": space_id})
        found: dict[str, int | None] = {}
        for row in rows:
            consistent: bool = (
                len(row["revision_keys"]) == 1
                and row["profiles"] == [profile_hash]
                and len(row["counts"]) == 1
                and sorted(row["indexes"]) == list(range(row["counts"][0]))
            )
            revisions: list[int] = row["revisions"]
            found[row["record_id"]] = (
                (revisions[0] if revisions else None) if consistent else INCONSISTENT_REVISION
            )
        return found

    async def _is_current(
        self, entry: ProjectionEntryDto, *, profile_hash: str, digest: str
    ) -> bool:
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _EXISTING, {"space_id": entry.space_id, "record_id": entry.key.record_id}
            )
        if not rows:
            return False
        wanted: tuple[str, str, str] = (revision_key(entry.key.revision), profile_hash, digest)
        counts: set[int] = {row["chunk_count"] for row in rows}
        return (
            all(
                (row["revision_key"], row["profile_hash"], row["content_hash"]) == wanted
                for row in rows
            )
            and len(counts) == 1
            and sorted(row["chunk_index"] for row in rows) == list(range(counts.pop()))
        )

    async def _replace(
        self, transaction: Neo4jTransaction, prepared: SemanticPreparedEntryDto
    ) -> None:
        entry: ProjectionEntryDto = prepared.entry
        await transaction.run(
            _DELETE_RECORD, {"space_id": entry.space_id, "record_id": entry.key.record_id}
        )
        if not prepared.chunks:
            return  # an empty text has no chunks; `--verify` reports the record as missing
        await transaction.run(
            _CREATE_CHUNKS,
            {
                "space_id": entry.space_id,
                "record_id": entry.key.record_id,
                "record_type": entry.record.record_type,
                "revision": entry.key.revision,
                "revision_key": revision_key(entry.key.revision),
                "profile_hash": prepared.profile_hash,
                "content_hash": prepared.content_hash,
                "chunk_count": len(prepared.chunks),
                "chunks": _chunk_rows(prepared),
            },
        )


def _chunk_rows(prepared: SemanticPreparedEntryDto) -> list[dict[str, Any]]:
    entry: ProjectionEntryDto = prepared.entry
    rows: Sequence[EmbeddedChunkDto] = prepared.chunks
    return [
        {
            "key": embedding_key(
                entry.space_id,
                entry.key.record_id,
                entry.key.revision,
                prepared.profile_hash,
                chunk.index,
            ),
            "index": chunk.index,
            "token_start": chunk.token_start,
            "token_end": chunk.token_end,
            "vector": list(chunk.vector),
        }
        for chunk in rows
    ]
