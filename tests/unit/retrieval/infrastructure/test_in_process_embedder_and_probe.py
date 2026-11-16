"""Per-call embedding (loaded once, off the event loop) and the no-side-effect status probe."""

from pathlib import Path
from typing import Any

import pytest
from tests.support.retrieval.fake_embedding import PROFILE, HashSession, WordTokenizer

from noesis.bounded_context.retrieval.application.ports.embedding import EmbedderUnavailableError
from noesis.bounded_context.retrieval.domain.enums import SemanticModeEnum
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding import (
    onnx_bge_engine,
    semantic_runtime_probe,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.in_process_text_embedder import (
    InProcessTextEmbedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    ModelCache,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
    OnnxBgeEngine,
    load_engine,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.semantic_runtime_probe import (
    SemanticRuntimeProbe,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.socket_text_embedder import (
    SocketTextEmbedder,
)

pytestmark = pytest.mark.unit


def counting_loader() -> tuple[list[int], Any]:
    loads: list[int] = []

    def load() -> OnnxBgeEngine:
        loads.append(1)
        return OnnxBgeEngine(WordTokenizer(), HashSession(), PROFILE)

    return loads, load


async def test_the_model_loads_once_on_first_use_only() -> None:
    loads, load = counting_loader()
    embedder = InProcessTextEmbedder(PROFILE, load)

    assert embedder.profile() == PROFILE
    assert loads == []
    await embedder.embed_query("a b")
    passages = await embedder.embed_passages(["c d e"])

    assert loads == [1]
    assert passages[0].token_count == 3


async def test_bounds_are_checked_before_loading() -> None:
    loads, load = counting_loader()
    embedder = InProcessTextEmbedder(PROFILE, load)

    with pytest.raises(EmbedderUnavailableError):
        await embedder.embed_query("x" * 32_001)
    with pytest.raises(EmbedderUnavailableError):
        await embedder.embed_passages(["x"] * 33)
    assert loads == []


async def test_a_loaded_model_of_another_profile_is_refused() -> None:
    other = PROFILE.model_copy(update={"artifact_sha256": "other"})
    embedder = InProcessTextEmbedder(
        other, lambda: OnnxBgeEngine(WordTokenizer(), HashSession(), PROFILE)
    )

    with pytest.raises(EmbedderUnavailableError, match="another profile"):
        await embedder.embed_query("x")


def test_load_engine_without_a_prepared_model_names_prepare(tmp_path: Path) -> None:
    pytest.importorskip("onnxruntime")

    with pytest.raises(EmbedderUnavailableError, match="model prepare"):
        load_engine(ModelCache(tmp_path))


def test_load_engine_without_the_optional_dependency_names_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def no_onnx(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "onnxruntime":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_onnx)

    with pytest.raises(EmbedderUnavailableError, match="semantic"):
        onnx_bge_engine.load_engine(ModelCache(tmp_path))


@pytest.mark.parametrize(
    ("mode", "installed", "state"),
    [
        (SemanticModeEnum.OFF, True, "off"),
        (SemanticModeEnum.RESIDENT, False, "absent"),
        (SemanticModeEnum.PER_CALL, True, "unavailable"),
        (SemanticModeEnum.RESIDENT, True, "unavailable"),
    ],
)
async def test_the_probe_reports_state_without_loading_or_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: SemanticModeEnum,
    installed: bool,
    state: str,
) -> None:
    monkeypatch.setattr(semantic_runtime_probe, "semantic_dependency_installed", lambda: installed)
    socket = tmp_path / "absent.sock"
    probe = SemanticRuntimeProbe(
        mode=mode,
        cache=ModelCache(tmp_path / "models"),
        client=SocketTextEmbedder(PROFILE, socket) if mode is SemanticModeEnum.RESIDENT else None,
    )

    found = await probe.diagnostics()

    assert found["state"] == state
    assert found["mode"] == mode.value
    assert found["model"]["prepared"] is False  # type: ignore[index]
    assert not socket.exists()
    assert not (tmp_path / "models").exists()
    if state != "off":
        assert "next_step" in found


async def test_the_probe_reports_a_running_resident_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Prepared(ModelCache):
        def is_prepared(self) -> bool:
            return True

    class Pinging(SocketTextEmbedder):
        async def ping(self) -> dict[str, Any]:
            return {"ok": True}

    monkeypatch.setattr(semantic_runtime_probe, "semantic_dependency_installed", lambda: True)
    probe = SemanticRuntimeProbe(
        mode=SemanticModeEnum.RESIDENT,
        cache=Prepared(tmp_path),
        client=Pinging(PROFILE, tmp_path / "s.sock"),
    )

    found = await probe.diagnostics()

    assert found["runtime"] == "running"
    assert found["state"] == "configured"
