"""The embedding profile: JSON form and a fingerprint that changes with any field."""

import pytest

from noesis.bounded_context.retrieval.domain.value_objects import EmbeddingProfile

pytestmark = pytest.mark.unit


def profile(**changes: object) -> EmbeddingProfile:
    fields: dict[str, object] = {
        "model": "m",
        "artifact_revision": "r",
        "artifact_sha256": "a",
        "tokenizer_sha256": "t",
        "runtime": "onnxruntime-cpu",
        "quantization": "none",
        "dimensions": 384,
        "similarity": "cosine",
        "query_instruction": "q: ",
        "chunk_policy": "c1",
        "query_policy": "p1",
    }
    return EmbeddingProfile.model_validate(fields | changes)


def test_the_json_form_round_trips() -> None:
    assert EmbeddingProfile.model_validate(profile().as_json()) == profile()


def test_the_fingerprint_is_stable() -> None:
    assert profile().fingerprint() == profile().fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_sha256": "b"},
        {"tokenizer_sha256": "u"},
        {"query_instruction": ""},
        {"chunk_policy": "c2"},
        {"quantization": "int8"},
        {"dimensions": 768},
    ],
)
def test_any_change_changes_the_fingerprint(change: dict[str, object]) -> None:
    assert profile(**change).fingerprint() != profile().fingerprint()
