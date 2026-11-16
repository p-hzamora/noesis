"""`ITextEmbedder` that asks the resident embedder over its Unix socket (resident mode).

Never starts the runtime: when nothing listens, every call fails fast with
`EmbedderUnavailableError`. Bounded by a 250 ms connect timeout, a 2 s query deadline and a
30 s deadline per passage batch; every reply vector is checked (size, finite, unit length).
"""

import asyncio
import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from ....application.ports.embedding import (
    MAX_PASSAGES_PER_REQUEST,
    MAX_QUERY_CHARACTERS,
    EmbeddedChunkDto,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
    ITextEmbedder,
)
from ....domain.value_objects import EmbeddingProfile
from .embedder_protocol import (
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    encoded_size,
    read_frame,
    write_frame,
)
from .vector_checks import validate_vector

CONNECT_TIMEOUT_SECONDS: float = 0.25
QUERY_DEADLINE_SECONDS: float = 2.0
BATCH_DEADLINE_SECONDS: float = 30.0


class SocketTextEmbedder(ITextEmbedder):
    """Client of `noesis index embedder serve`.

    Args:
        profile: The configured profile; the runtime must serve the same fingerprint.
        socket: The runtime's socket path.
    """

    def __init__(self, profile: EmbeddingProfile, socket: Path) -> None:
        self._profile: EmbeddingProfile = profile
        self._socket: Path = socket

    def profile(self) -> EmbeddingProfile:
        """The configured profile."""
        return self._profile

    async def ping(self) -> dict[str, Any]:
        """The runtime's ping reply (protocol, profile, load).

        Raises:
            EmbedderUnavailableError: Nothing listens or the reply is malformed.
        """
        return await self._call({"op": "ping"}, deadline=CONNECT_TIMEOUT_SECONDS * 4)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """One unit vector from the runtime within the query deadline."""
        if len(text) > MAX_QUERY_CHARACTERS:
            raise EmbedderUnavailableError(
                f"semantic search accepts at most {MAX_QUERY_CHARACTERS} characters"
            )
        reply: dict[str, Any] = await self._call(
            {"op": "query", "texts": [text]}, deadline=QUERY_DEADLINE_SECONDS
        )
        vector: Any = reply.get("vector")
        if not isinstance(vector, list):
            raise EmbedderUnavailableError("the embedder reply has no vector")
        return validate_vector(vector, self._profile.dimensions)

    async def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedPassageDto]:
        """Embed in requests of at most 32 passages, each within the batch deadline."""
        found: list[EmbeddedPassageDto] = []
        for start in range(0, len(texts), MAX_PASSAGES_PER_REQUEST):
            group: list[str] = list(texts[start : start + MAX_PASSAGES_PER_REQUEST])
            reply: dict[str, Any] = await self._call(
                {"op": "passages", "texts": group}, deadline=BATCH_DEADLINE_SECONDS
            )
            passages: Any = reply.get("passages")
            if not isinstance(passages, list) or len(passages) != len(group):
                raise EmbedderUnavailableError("the embedder reply has the wrong passage count")
            found.extend(self._passage(passage) for passage in passages)
        return found

    def _passage(self, raw: Any) -> EmbeddedPassageDto:
        try:
            chunks: tuple[EmbeddedChunkDto, ...] = tuple(
                EmbeddedChunkDto(
                    index=int(chunk["index"]),
                    token_start=int(chunk["token_start"]),
                    token_end=int(chunk["token_end"]),
                    vector=validate_vector(chunk["vector"], self._profile.dimensions),
                )
                for chunk in raw["chunks"]
            )
            return EmbeddedPassageDto(token_count=int(raw["token_count"]), chunks=chunks)
        except (KeyError, TypeError, ValueError) as error:
            raise EmbedderUnavailableError("the embedder reply is malformed") from error

    async def _call(self, request: dict[str, Any], *, deadline: float) -> dict[str, Any]:
        message: dict[str, Any] = {
            "protocol": PROTOCOL_VERSION,
            "profile": self._profile.fingerprint(),
            "id": uuid4().hex,
            **request,
        }
        if encoded_size(message) > MAX_REQUEST_BYTES:
            raise EmbedderUnavailableError("the embedding request exceeds 1 MiB")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._socket)), CONNECT_TIMEOUT_SECONDS
            )
        except (OSError, TimeoutError) as error:
            raise EmbedderUnavailableError(
                "the resident embedder is not running; start `noesis index embedder serve`"
            ) from error
        try:
            await write_frame(writer, message)
            reply: dict[str, Any] = await asyncio.wait_for(
                read_frame(reader, max_bytes=MAX_REPLY_BYTES), deadline
            )
        except TimeoutError as error:
            raise EmbedderUnavailableError("the resident embedder timed out") from error
        except (OSError, ProtocolError) as error:
            raise EmbedderUnavailableError(f"the resident embedder failed: {error}") from error
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        if reply.get("id") != message["id"] or reply.get("protocol") != PROTOCOL_VERSION:
            raise EmbedderUnavailableError("the resident embedder sent a mismatched reply")
        if not reply.get("ok"):
            raise EmbedderUnavailableError(
                f"the resident embedder refused the request: {reply.get('error', 'unknown')}"
            )
        return reply
