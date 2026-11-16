"""What a semantic projection is built with: model artifact, runtime and text policies."""

import hashlib
import json

from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.domain.value_objects import ValueObject


class EmbeddingProfile(ValueObject):
    """Everything that changes the vectors a projection holds.

    Two profiles are compatible only when every field is equal; vectors of different profiles
    are never compared (one physical index holds one profile per space).

    Attributes:
        model: Model name (`BAAI/bge-small-en-v1.5`).
        artifact_revision: Immutable upstream revision the artifact files were taken from.
        artifact_sha256: Digest of the model file.
        tokenizer_sha256: Digest of the tokenizer file.
        runtime: Inference runtime (`onnxruntime-cpu`).
        quantization: `none`, or the quantization of the model file.
        dimensions: Vector size.
        similarity: Vector similarity (`cosine`).
        query_instruction: Prefix added once to every query, never to a passage.
        chunk_policy: Version of the passage windowing rule.
        query_policy: Version of the query windowing and averaging rule.
    """

    model: str
    artifact_revision: str
    artifact_sha256: str
    tokenizer_sha256: str
    runtime: str
    quantization: str
    dimensions: int
    similarity: str
    query_instruction: str
    chunk_policy: str
    query_policy: str

    def as_json(self) -> dict[str, JsonValue]:
        """The profile as plain JSON (what is persisted and reported)."""
        return dict(self.model_dump(mode="json"))

    def fingerprint(self) -> str:
        """A stable digest of the whole profile: the `profile_hash` of every chunk node."""
        canonical: str = json.dumps(self.as_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
