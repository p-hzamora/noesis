"""Fakes for the embedding runtime: a word tokenizer, an ONNX-shaped session, an engine."""

import hashlib
import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from noesis.bounded_context.retrieval.application.ports.embedding import (
    EmbeddedChunkDto,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
    ITextEmbedder,
)
from noesis.bounded_context.retrieval.domain.policies.token_window_policy import TokenWindowPolicy
from noesis.bounded_context.retrieval.domain.value_objects import EmbeddingProfile
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    BGE_SMALL_EN_V15,
)

DIMENSIONS: int = 384
CLS: int = 101
SEP: int = 102
PROFILE: EmbeddingProfile = BGE_SMALL_EN_V15.profile()


class WordEncoding:
    """Token ids of a whitespace tokenizer."""

    def __init__(self, ids: list[int]) -> None:
        self._ids: list[int] = ids

    @property
    def ids(self) -> list[int]:
        """The ids."""
        return self._ids


class WordTokenizer:
    """One token per whitespace-separated word; ids are stable digests >= 1000."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def encode(self, sequence: str, add_special_tokens: bool = True) -> WordEncoding:
        """Encode, recording the call."""
        self.calls.append((sequence, add_special_tokens))
        ids: list[int] = [word_id(word) for word in sequence.split()]
        return WordEncoding([CLS, *ids, SEP] if add_special_tokens else ids)

    def token_to_id(self, token: str) -> int | None:
        """`[CLS]` and `[SEP]` only."""
        return {"[CLS]": CLS, "[SEP]": SEP}.get(token)


def word_id(word: str) -> int:
    """A stable id for a word."""
    return 1000 + int(hashlib.sha256(word.encode()).hexdigest(), 16) % 20_000


class HashSession:
    """Returns, for each row, a CLS vector derived from the row's token ids."""

    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    def run(self, output_names: Sequence[str] | None, input_feed: dict[str, Any]) -> list[Any]:
        """`last_hidden_state` of shape (rows, width, 384); only position 0 matters."""
        self.inputs.append(input_feed)
        ids = input_feed["input_ids"]
        hidden = np.zeros((ids.shape[0], ids.shape[1], DIMENSIONS), dtype=np.float32)
        for row in range(ids.shape[0]):
            seed: int = int(ids[row].sum()) % 10_007 + 1
            hidden[row, 0, :] = [math.sin(seed * (i + 1)) for i in range(DIMENSIONS)]
        return [hidden]


def unit(seed: int) -> tuple[float, ...]:
    """A deterministic unit vector."""
    raw: list[float] = [math.sin(seed * (i + 1)) + 0.01 for i in range(DIMENSIONS)]
    norm: float = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


def bag_of_words(words: Sequence[str]) -> tuple[float, ...]:
    """A unit vector with one hashed dimension per distinct lower-case word (plus a floor).

    Cosine between two such vectors grows with shared words, so tests can predict ranks.
    """
    raw: list[float] = [0.001] * DIMENSIONS
    for word in {word.lower().strip(".,;:!?") for word in words}:
        raw[word_id(word) % DIMENSIONS] += 1.0
    norm: float = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


class FakeEngine:
    """An engine-shaped fake: words are tokens; vectors are bags of words (no instruction)."""

    def __init__(self, profile: EmbeddingProfile = PROFILE) -> None:
        self._profile: EmbeddingProfile = profile
        self.queries: list[str] = []
        self.passages: list[str] = []
        self.fail: bool = False

    @property
    def profile(self) -> EmbeddingProfile:
        """The profile."""
        return self._profile

    def embed_passage(self, text: str) -> EmbeddedPassageDto:
        """Windows of words."""
        if self.fail:
            raise EmbedderUnavailableError("engine down")
        self.passages.append(text)
        words: list[str] = text.split()
        windows = TokenWindowPolicy().windows(len(words))
        return EmbeddedPassageDto(
            token_count=len(words),
            chunks=tuple(
                EmbeddedChunkDto(
                    index=w.index,
                    token_start=w.start,
                    token_end=w.end,
                    vector=bag_of_words(words[w.start : w.end]),
                )
                for w in windows
            ),
        )

    def embed_query(self, text: str) -> tuple[float, ...]:
        """A digest vector of the query."""
        if self.fail:
            raise EmbedderUnavailableError("engine down")
        self.queries.append(text)
        return bag_of_words(text.split())


class FakeTextEmbedder(ITextEmbedder):
    """`ITextEmbedder` over `FakeEngine`, with a failure switch."""

    def __init__(self, engine: FakeEngine | None = None) -> None:
        self.engine: FakeEngine = engine or FakeEngine()

    def profile(self) -> EmbeddingProfile:
        """The engine's profile."""
        return self.engine.profile

    async def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedPassageDto]:
        """Each passage through the engine."""
        return [self.engine.embed_passage(text) for text in texts]

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """The query through the engine."""
        return self.engine.embed_query(text)
