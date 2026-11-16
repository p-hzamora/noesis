"""Text embedding and its runtime diagnostics."""

from .i_semantic_runtime_probe import ISemanticRuntimeProbe
from .i_text_embedder import (
    MAX_PASSAGES_PER_REQUEST,
    MAX_QUERY_CHARACTERS,
    EmbeddedChunkDto,
    EmbeddedPassageDto,
    EmbedderUnavailableError,
    ITextEmbedder,
)

__all__ = [
    "MAX_PASSAGES_PER_REQUEST",
    "MAX_QUERY_CHARACTERS",
    "EmbeddedChunkDto",
    "EmbeddedPassageDto",
    "EmbedderUnavailableError",
    "ISemanticRuntimeProbe",
    "ITextEmbedder",
]
