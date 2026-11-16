"""C5b CLI surfaces: model prepare, embedder serve, `--semantic`, registration by mode (AC-215).

Help and usage errors do no store, model, network or process work; nothing here downloads.
"""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.support.knowledge_cli_support import run_json, use_closed_store
from tests.unit.retrieval.infrastructure.test_model_artifacts import Fetcher, tiny_artifact

from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    ModelCache,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.socket_text_embedder import (
    SocketTextEmbedder,
)
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic import (
    Neo4jSemanticCandidateSource,
    Neo4jSemanticProjectionAdapter,
)
from noesis.core import load_environment
from noesis.interfaces.cli import run
from noesis.interfaces.cli.bootstrap import retrieval_handlers_builder
from noesis.interfaces.cli.commands import index_commands
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "argv",
    [
        ["index", "model", "prepare", "--help"],
        ["index", "embedder", "serve", "--help"],
        ["index", "model", "--help"],
        ["search", "--help"],
    ],
)
def test_help_does_no_io(argv: list[str], isolated_environment: Path) -> None:
    assert run(argv) == 0
    assert not (isolated_environment / ".cache").exists()


def test_search_semantic_in_off_mode_is_a_usage_error_before_any_store_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_RETRIEVAL_SEMANTIC_MODE", "off")

    code = run(["search", "leases", "--semantic"])

    assert code == 2
    assert "NOESIS_RETRIEVAL_SEMANTIC_MODE" in capsys.readouterr().err


def test_a_bad_mode_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_RETRIEVAL_SEMANTIC_MODE", "always")

    code, envelope = run_json(capsys, ["search", "leases"])

    assert code != 0
    assert envelope["ok"] is False


def test_model_prepare_reports_the_pinned_artifact(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        index_commands, "model_cache", lambda env: ModelCache(tmp_path, tiny_artifact())
    )
    monkeypatch.setattr(index_commands, "https_fetch", Fetcher())

    code, envelope = run_json(capsys, ["index", "model", "prepare"])
    again_code, again = run_json(capsys, ["index", "model", "prepare"])

    assert code == again_code == 0
    assert envelope["result"]["downloaded"] is True  # type: ignore[index]
    assert again["result"]["downloaded"] is False  # type: ignore[index]
    assert envelope["result"]["licence"] == "MIT"  # type: ignore[index]


def test_model_prepare_failure_is_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def offline(url: str, target: Path) -> None:
        raise OSError("network unreachable")

    monkeypatch.setattr(
        index_commands, "model_cache", lambda env: ModelCache(tmp_path, tiny_artifact())
    )
    monkeypatch.setattr(index_commands, "https_fetch", offline)

    code, envelope = run_json(capsys, ["index", "model", "prepare"])

    assert code == 1
    assert envelope["error"]["code"] == "RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE"  # type: ignore[index]


def test_serve_without_the_optional_dependency_names_the_setup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(index_commands, "semantic_dependency_installed", lambda: False)

    code, envelope = run_json(capsys, ["index", "embedder", "serve"])

    assert code == 1
    assert "noesis[semantic]" in json.dumps(envelope)


def test_serve_without_a_prepared_model_names_prepare(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(index_commands, "semantic_dependency_installed", lambda: True)

    code, envelope = run_json(capsys, ["index", "embedder", "serve"])

    assert code == 1
    assert "model prepare" in json.dumps(envelope)


def _client() -> Neo4jClient:
    return Neo4jClient(
        Neo4jConnectionSettings(uri="bolt://127.0.0.1:1", user="neo4j", password=SecretStr("x"))
    )


@pytest.mark.parametrize(
    ("mode", "installed", "opt_in", "writers", "sources"),
    [
        ("off", True, True, 0, 0),
        ("resident", False, True, 0, 0),
        ("resident", True, False, 1, 1),
        ("per-call", True, False, 1, 0),
        ("per-call", True, True, 1, 1),
    ],
)
def test_registration_follows_the_mode_and_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    installed: bool,
    opt_in: bool,
    writers: int,
    sources: int,
) -> None:
    monkeypatch.setattr(
        retrieval_handlers_builder, "semantic_dependency_installed", lambda: installed
    )
    monkeypatch.setenv("NOESIS_RETRIEVAL_SEMANTIC_MODE", mode)
    environment = load_environment(tmp_path / "missing.env")  # type: ignore[operator]

    registered = retrieval_handlers_builder.registered_projections(
        _client(), environment, semantic_opt_in=opt_in
    )

    assert len(registered.writers) == writers
    assert len(registered.candidate_sources) == sources
    assert all(isinstance(w, Neo4jSemanticProjectionAdapter) for w in registered.writers)
    assert all(isinstance(s, Neo4jSemanticCandidateSource) for s in registered.candidate_sources)


def test_the_resident_socket_lives_under_the_runtime_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NOESIS_RETRIEVAL_RUNTIME_DIR", str(tmp_path / "run"))
    environment = load_environment(tmp_path / "missing.env")  # type: ignore[operator]

    socket = retrieval_handlers_builder.embedder_socket(environment)

    assert socket.parent == tmp_path / "run" / "noesis"
    assert socket.name.startswith("embedder-")
    probe = retrieval_handlers_builder._probe(_client(), environment)
    assert probe is not None
    assert isinstance(
        SocketTextEmbedder(
            retrieval_handlers_builder.model_cache(environment).artifact.profile(), socket
        ),
        SocketTextEmbedder,
    )
