"""`ISemanticRuntimeProbe`: what `index status` says about semantic setup.

It checks the optional dependency by module lookup (no import), the model cache by manifest and
sizes (no hashing, no loading), pings a resident runtime (never starts one) and reads the
vector index state. Nothing is downloaded, loaded or started.
"""

import importlib.util
from typing import Any

from noesis.shared_kernel.domain import JsonValue

from ....application.ports.embedding import EmbedderUnavailableError, ISemanticRuntimeProbe
from ....domain.enums import SemanticModeEnum
from ..semantic.neo4j_vector_index_inspector import Neo4jVectorIndexInspector
from .model_artifacts import ModelCache
from .socket_text_embedder import SocketTextEmbedder

OPTIONAL_MODULES: tuple[str, ...] = ("numpy", "onnxruntime", "tokenizers")
SETUP_NEXT_STEP: str = (
    "Install the optional extra (`uv tool install --force 'noesis[semantic]'`), run "
    "`noesis index model prepare`, start `noesis index embedder serve`, then "
    "`noesis index rebuild --yes`."
)


def semantic_dependency_installed() -> bool:
    """Whether the optional `semantic` modules can be imported (they are not imported here)."""
    return all(importlib.util.find_spec(name) is not None for name in OPTIONAL_MODULES)


class SemanticRuntimeProbe(ISemanticRuntimeProbe):
    """Diagnostics of one configuration.

    Args:
        mode: The configured semantic mode.
        cache: The model cache.
        client: The resident runtime's client; null outside resident mode.
        inspector: The vector index inspector; null when no store is wired.
    """

    def __init__(
        self,
        *,
        mode: SemanticModeEnum,
        cache: ModelCache,
        client: SocketTextEmbedder | None = None,
        inspector: Neo4jVectorIndexInspector | None = None,
    ) -> None:
        self._mode: SemanticModeEnum = mode
        self._cache: ModelCache = cache
        self._client: SocketTextEmbedder | None = client
        self._inspector: Neo4jVectorIndexInspector | None = inspector

    async def diagnostics(self) -> dict[str, JsonValue]:
        """Mode, dependency, model, runtime and vector index, with a next step when unusable."""
        installed: bool = semantic_dependency_installed()
        found: dict[str, JsonValue] = {
            "mode": self._mode.value,
            "dependency_installed": installed,
            "model": {
                "name": self._cache.artifact.model,
                "revision": self._cache.artifact.revision,
                "prepared": self._cache.is_prepared(),
                "directory": str(self._cache.directory),
            },
            "profile_hash": self._cache.artifact.profile().fingerprint(),
            "runtime": await self._runtime(),
        }
        if self._inspector is not None:
            found["vector_index"] = (await self._inspector.state()).as_json()
        if self._mode is SemanticModeEnum.OFF:
            found["state"] = "off"
        elif not installed:
            found["state"] = "absent"
            found["next_step"] = SETUP_NEXT_STEP
        elif not self._cache.is_prepared():
            found["state"] = "unavailable"
            found["next_step"] = "Run `noesis index model prepare`."
        elif self._mode is SemanticModeEnum.RESIDENT and found["runtime"] != "running":
            found["state"] = "unavailable"
            found["next_step"] = "Start `noesis index embedder serve` (it is never auto-started)."
        else:
            found["state"] = "configured"
        return found

    async def _runtime(self) -> JsonValue:
        if self._mode is not SemanticModeEnum.RESIDENT or self._client is None:
            return "not_applicable" if self._mode is not SemanticModeEnum.RESIDENT else "unknown"
        try:
            reply: dict[str, Any] = await self._client.ping()
        except EmbedderUnavailableError:
            return "not_running"
        return "running" if reply.get("ok") else "not_running"
