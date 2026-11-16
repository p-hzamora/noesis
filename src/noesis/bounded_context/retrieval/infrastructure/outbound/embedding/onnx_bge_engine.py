"""Synchronous bge inference over token windows with onnxruntime (CPU) and `tokenizers`.

FastEmbed's text API truncates every input at 512 tokens and takes strings, not token windows,
so the engine drives the same CPU ONNX runtime directly: the tokenizer runs once over the whole
text without special tokens, `TokenWindowPolicy` cuts it into windows, and each window is
embedded as `[CLS] window [SEP]` with CLS pooling and L2 normalisation (bge's recipe). A query
gets the instruction exactly once, ahead of every window of the query.

Heavy imports (`onnxruntime`, `tokenizers`) happen only in `load_engine`; this module needs
only numpy, which the optional `semantic` extra installs.
"""

import math
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from ....application.ports.embedding import (
    EmbeddedChunkDto,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
)
from ....domain.policies.token_window_policy import (
    MODEL_MAX_TOKENS,
    OVERLAP_TOKENS,
    SPECIAL_TOKENS,
    TokenWindowPolicy,
)
from ....domain.value_objects import EmbeddingProfile, TokenWindow
from .model_artifacts import ModelCache, ModelCacheError

WINDOWS_PER_RUN: int = 16


class EncodingLike(Protocol):
    """What the engine reads from a tokenizer's encoding."""

    @property
    def ids(self) -> list[int]:
        """Token ids."""
        ...


class TokenizerLike(Protocol):
    """The part of `tokenizers.Tokenizer` the engine uses."""

    def encode(self, sequence: str, add_special_tokens: bool = True) -> EncodingLike:
        """Encode one text."""
        ...

    def token_to_id(self, token: str) -> int | None:
        """Id of a special token."""
        ...


class SessionLike(Protocol):
    """The part of `onnxruntime.InferenceSession` the engine uses."""

    def run(self, output_names: Sequence[str] | None, input_feed: dict[str, Any]) -> list[Any]:
        """Run the model."""
        ...


class OnnxBgeEngine:
    """Embeds passages and queries; not thread-safe (one inference at a time).

    Args:
        tokenizer: The pinned tokenizer, with truncation and padding disabled.
        session: The ONNX session of the pinned model.
        profile: The profile these produce.
    """

    def __init__(
        self, tokenizer: TokenizerLike, session: SessionLike, profile: EmbeddingProfile
    ) -> None:
        cls_id: int | None = tokenizer.token_to_id("[CLS]")
        sep_id: int | None = tokenizer.token_to_id("[SEP]")
        if cls_id is None or sep_id is None:
            raise EmbedderUnavailableError("the tokenizer has no [CLS]/[SEP] tokens")
        self._tokenizer: TokenizerLike = tokenizer
        self._session: SessionLike = session
        self._profile: EmbeddingProfile = profile
        self._cls: int = cls_id
        self._sep: int = sep_id
        self._passages: TokenWindowPolicy = TokenWindowPolicy()
        self._instruction: list[int] = self.tokens(profile.query_instruction)
        query_window: int = MODEL_MAX_TOKENS - SPECIAL_TOKENS - len(self._instruction)
        self._queries: TokenWindowPolicy = TokenWindowPolicy(
            window=query_window, overlap=min(OVERLAP_TOKENS, query_window - 1)
        )

    @property
    def profile(self) -> EmbeddingProfile:
        """The profile."""
        return self._profile

    def tokens(self, text: str) -> list[int]:
        """Content token ids of `text`, no special tokens, never truncated."""
        return list(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def embed_passage(self, text: str) -> EmbeddedPassageDto:
        """Every window of one passage (no instruction); none for an empty text."""
        ids: list[int] = self.tokens(text)
        windows: tuple[TokenWindow, ...] = self._passages.windows(len(ids))
        chunks: list[EmbeddedChunkDto] = []
        for start in range(0, len(windows), WINDOWS_PER_RUN):
            group: tuple[TokenWindow, ...] = windows[start : start + WINDOWS_PER_RUN]
            vectors: list[tuple[float, ...]] = self._run(
                [[self._cls, *ids[w.start : w.end], self._sep] for w in group]
            )
            chunks.extend(
                EmbeddedChunkDto(
                    index=window.index,
                    token_start=window.start,
                    token_end=window.end,
                    vector=vector,
                )
                for window, vector in zip(group, vectors, strict=True)
            )
        return EmbeddedPassageDto(token_count=len(ids), chunks=tuple(chunks))

    def embed_query(self, text: str) -> tuple[float, ...]:
        """The instruction once plus each window of the query; windows averaged, renormalised.

        Raises:
            EmbedderUnavailableError: The query has no tokens.
        """
        ids: list[int] = self.tokens(text)
        windows: tuple[TokenWindow, ...] = self._queries.windows(len(ids))
        if not windows:
            raise EmbedderUnavailableError("an empty query has no embedding")
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(windows), WINDOWS_PER_RUN):
            group: tuple[TokenWindow, ...] = windows[start : start + WINDOWS_PER_RUN]
            vectors.extend(
                self._run(
                    [
                        [self._cls, *self._instruction, *ids[w.start : w.end], self._sep]
                        for w in group
                    ]
                )
            )
        mean = np.mean(np.asarray(vectors, dtype=np.float64), axis=0)
        return _normalised(mean, self._profile.dimensions)

    def _run(self, sequences: list[list[int]]) -> list[tuple[float, ...]]:
        width: int = max(len(sequence) for sequence in sequences)
        if width > MODEL_MAX_TOKENS:
            raise EmbedderUnavailableError(f"a window of {width} tokens exceeds the model maximum")
        input_ids = np.zeros((len(sequences), width), dtype=np.int64)
        mask = np.zeros((len(sequences), width), dtype=np.int64)
        for row, sequence in enumerate(sequences):
            input_ids[row, : len(sequence)] = sequence
            mask[row, : len(sequence)] = 1
        outputs: list[Any] = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": mask,
                "token_type_ids": np.zeros_like(input_ids),
            },
        )
        hidden = np.asarray(outputs[0])
        return [
            _normalised(hidden[row, 0, :], self._profile.dimensions)
            for row in range(len(sequences))
        ]


def _normalised(vector: Any, dimensions: int) -> tuple[float, ...]:
    """`vector` scaled to unit length, after checking its size and values."""
    values = np.asarray(vector, dtype=np.float64)
    if values.shape != (dimensions,) or not bool(np.all(np.isfinite(values))):
        raise EmbedderUnavailableError("the model produced an invalid vector")
    norm: float = float(np.linalg.norm(values))
    if norm == 0.0 or not math.isfinite(norm):
        raise EmbedderUnavailableError("the model produced a zero vector")
    return tuple(float(value) for value in values / norm)


def load_engine(cache: ModelCache, *, threads: int | None = None) -> OnnxBgeEngine:
    """Load the verified artifact from the offline cache (no network).

    Raises:
        EmbedderUnavailableError: The optional dependency is missing or the cache is not
            prepared, incomplete or corrupt.
    """
    try:
        import onnxruntime  # the optional `semantic` extra
        from tokenizers import Tokenizer
    except ImportError as error:
        raise EmbedderUnavailableError(
            "the optional semantic dependencies are not installed (noesis[semantic])"
        ) from error
    try:
        cache.verify()
    except ModelCacheError as error:
        raise EmbedderUnavailableError(f"{error}; run `noesis index model prepare`") from error
    tokenizer = Tokenizer.from_file(str(cache.path_of(cache.artifact.tokenizer_file.name)))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    options = onnxruntime.SessionOptions()
    if threads is not None:
        options.intra_op_num_threads = threads
    session = onnxruntime.InferenceSession(
        str(cache.path_of(cache.artifact.model_file.name)),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return OnnxBgeEngine(tokenizer, session, cache.artifact.profile())
