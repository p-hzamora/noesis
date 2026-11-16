"""Q-204 / AC-212: the pinned artifact, offline cache checks and atomic preparation."""

import hashlib
from pathlib import Path

import pytest

from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.model_artifacts import (
    BGE_SMALL_EN_V15,
    MANIFEST_NAME,
    ArtifactFileDto,
    ModelArtifactDto,
    ModelCache,
    ModelCacheError,
)

pytestmark = pytest.mark.unit

CONTENT: dict[str, bytes] = {"model.onnx": b"onnx-bytes", "tokenizer.json": b'{"t": 1}'}


def tiny_artifact() -> ModelArtifactDto:
    return ModelArtifactDto(
        model="org/tiny",
        repository="org/tiny",
        revision="a" * 40,
        licence="MIT",
        quantization="none",
        dimensions=384,
        files=tuple(
            ArtifactFileDto(
                source=f"src/{name}",
                name=name,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
            )
            for name, data in CONTENT.items()
        ),
    )


class Fetcher:
    def __init__(self, content: dict[str, bytes] | None = None) -> None:
        self.content: dict[str, bytes] = content or CONTENT
        self.urls: list[str] = []

    def __call__(self, url: str, target: Path) -> None:
        self.urls.append(url)
        target.write_bytes(self.content[url.rsplit("/", 1)[-1]])


def test_the_default_artifact_is_pinned_to_an_immutable_revision() -> None:
    assert len(BGE_SMALL_EN_V15.revision) == 40
    assert BGE_SMALL_EN_V15.dimensions == 384
    assert BGE_SMALL_EN_V15.model_file.name == "model.onnx"
    assert BGE_SMALL_EN_V15.tokenizer_file.name == "tokenizer.json"
    profile = BGE_SMALL_EN_V15.profile()
    assert profile.query_instruction == "Represent this sentence for searching relevant passages: "
    assert profile.similarity == "cosine"


def test_an_empty_cache_is_not_prepared_and_verify_names_it(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())

    assert not cache.is_prepared()
    with pytest.raises(ModelCacheError, match="not prepared"):
        cache.verify()


def test_prepare_downloads_pinned_urls_verifies_and_completes_atomically(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())
    fetch = Fetcher()

    report = cache.prepare(fetch)

    assert report.downloaded
    assert report.size_bytes == sum(len(v) for v in CONTENT.values())
    assert all(f"/resolve/{'a' * 40}/src/" in url for url in fetch.urls)
    assert (cache.directory / MANIFEST_NAME).is_file()
    assert cache.is_prepared()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".prepare-")]


def test_prepare_twice_downloads_once(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())
    fetch = Fetcher()
    cache.prepare(fetch)

    again = cache.prepare(fetch)

    assert not again.downloaded
    assert len(fetch.urls) == len(CONTENT)


def test_a_corrupt_download_keeps_nothing(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())

    with pytest.raises(ModelCacheError, match="SHA-256"):
        cache.prepare(Fetcher({"model.onnx": b"onnx-BYTES", "tokenizer.json": b'{"t": 1}'}))

    assert not cache.directory.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".prepare-")]


def test_a_truncated_download_is_refused_by_size(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())

    with pytest.raises(ModelCacheError, match="bytes"):
        cache.prepare(Fetcher({"model.onnx": b"onnx", "tokenizer.json": b'{"t": 1}'}))


def test_a_corrupted_cache_fails_verify_and_prepare_repairs_it(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())
    cache.prepare(Fetcher())
    cache.path_of("model.onnx").write_bytes(b"onnx-BYTES")  # same size, other digest

    assert cache.is_prepared()  # the cheap check does not hash
    with pytest.raises(ModelCacheError, match="SHA-256"):
        cache.verify()
    assert cache.prepare(Fetcher()).downloaded
    cache.verify()


def test_a_missing_file_or_foreign_manifest_is_not_prepared(tmp_path: Path) -> None:
    cache = ModelCache(tmp_path, tiny_artifact())
    cache.prepare(Fetcher())
    (cache.directory / MANIFEST_NAME).write_text('{"model": "other"}', encoding="utf-8")
    assert not cache.is_prepared()

    cache.prepare(Fetcher())
    cache.path_of("tokenizer.json").unlink()
    assert not cache.is_prepared()
