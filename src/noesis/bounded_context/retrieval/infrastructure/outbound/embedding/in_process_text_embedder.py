"""`ITextEmbedder` that loads the model into this process on first use (per-call mode).

Loading costs seconds, so only explicit opt-ins (`search --semantic`, `index sync/rebuild`) wire
it. Inference runs in a worker thread so the event loop (and the lease heartbeat) keep running.
"""

import asyncio
from collections.abc import Callable, Sequence

from ....application.ports.embedding import (
    MAX_PASSAGES_PER_REQUEST,
    MAX_QUERY_CHARACTERS,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
    ITextEmbedder,
)
from ....domain.value_objects import EmbeddingProfile
from .onnx_bge_engine import OnnxBgeEngine


class InProcessTextEmbedder(ITextEmbedder):
    """Embeds with an engine loaded once, lazily, by `load`.

    Args:
        profile: The configured profile (known without loading).
        load: Builds the engine from the offline cache.
    """

    def __init__(self, profile: EmbeddingProfile, load: Callable[[], OnnxBgeEngine]) -> None:
        self._profile: EmbeddingProfile = profile
        self._load: Callable[[], OnnxBgeEngine] = load
        self._engine: OnnxBgeEngine | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    def profile(self) -> EmbeddingProfile:
        """The configured profile."""
        return self._profile

    async def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedPassageDto]:
        """Window and embed each passage in a worker thread."""
        if len(texts) > MAX_PASSAGES_PER_REQUEST:
            raise EmbedderUnavailableError(
                f"at most {MAX_PASSAGES_PER_REQUEST} passages per request"
            )
        engine: OnnxBgeEngine = await self._engine_loaded()
        return [await asyncio.to_thread(engine.embed_passage, text) for text in texts]

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed the query in a worker thread."""
        if len(text) > MAX_QUERY_CHARACTERS:
            raise EmbedderUnavailableError(
                f"semantic search accepts at most {MAX_QUERY_CHARACTERS} characters"
            )
        engine: OnnxBgeEngine = await self._engine_loaded()
        return await asyncio.to_thread(engine.embed_query, text)

    async def _engine_loaded(self) -> OnnxBgeEngine:
        async with self._lock:
            if self._engine is None:
                engine: OnnxBgeEngine = await asyncio.to_thread(self._load)
                if engine.profile != self._profile:
                    raise EmbedderUnavailableError("the loaded model has another profile")
                self._engine = engine
            return self._engine
