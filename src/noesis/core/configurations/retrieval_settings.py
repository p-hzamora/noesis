"""Settings for search and the index commands."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings
from .paths import default_model_cache_dir, default_runtime_root

DEFAULT_INDEX_LOCK_TTL_SECONDS: int = 300


class RetrievalSettings(AppBaseSettings):
    """Index leases, semantic search and the recall briefing.

    Attributes:
        index_lock_ttl_seconds: Seconds a sync or rebuild may hold a projection's lease without
            renewing it before another process may take it over (`NOESIS_INDEX_LOCK_TTL_SECONDS`).
        retrieval_semantic_mode: `resident` (default: use a running `noesis index embedder
            serve`), `per-call` (load the model only for explicit opt-ins) or `off`
            (`NOESIS_RETRIEVAL_SEMANTIC_MODE`).
        retrieval_model_cache_dir: Where `noesis index model prepare` puts the pinned model
            (`NOESIS_RETRIEVAL_MODEL_CACHE_DIR`; default `$XDG_CACHE_HOME/noesis/models`).
        retrieval_runtime_dir: Root of the embedder's socket directory
            (`NOESIS_RETRIEVAL_RUNTIME_DIR`; default `$XDG_RUNTIME_DIR`, else a private
            directory under the model cache).
        retrieval_embedder_threads: ONNX intra-op threads; null lets the runtime choose.
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    index_lock_ttl_seconds: int = Field(default=DEFAULT_INDEX_LOCK_TTL_SECONDS, gt=0)

    retrieval_semantic_mode: Literal["resident", "per-call", "off"] = "resident"
    retrieval_model_cache_dir: Path = Field(default_factory=default_model_cache_dir)
    retrieval_runtime_dir: Path | None = Field(default_factory=default_runtime_root)
    retrieval_embedder_threads: int | None = Field(default=None, gt=0)

    retrieval_briefing_timeout_seconds: float = Field(default=60, gt=0)
    retrieval_briefing_max_budget_usd: float = Field(default=0.50, gt=0)
    retrieval_briefing_max_evidence_chars: int = Field(default=24000, gt=0)
    retrieval_briefing_claude_bin: str = "claude"
