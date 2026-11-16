"""The pinned model artifact and its offline cache (Q-204).

The artifact is one immutable upstream revision of `BAAI/bge-small-en-v1.5`: its ONNX export
and tokenizer files, each with a fixed size and SHA-256. `noesis index model prepare` is the only
path that downloads: into a temporary directory under the cache, verified, completed by a
manifest and moved into place atomically. Every other call reads the cache offline and fails
with a prepare next step when it is missing or corrupt; there is no fallback model.
"""

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Final

from noesis.utils import FrozenObject

from ....domain.policies.token_window_policy import CHUNK_POLICY_VERSION, QUERY_POLICY_VERSION
from ....domain.value_objects import EmbeddingProfile

MANIFEST_NAME: Final[str] = "noesis-artifact.json"
QUERY_INSTRUCTION: Final[str] = "Represent this sentence for searching relevant passages: "
RUNTIME: Final[str] = "onnxruntime-cpu"
DOWNLOAD_BASE: Final[str] = "https://huggingface.co"

type Fetch = Callable[[str, Path], None]
"""Downloads a URL to a path (injected; tests never download)."""


class ModelCacheError(Exception):
    """The prepared model is missing, incomplete or corrupt."""


class ArtifactFileDto(FrozenObject):
    """One pinned file of the artifact.

    Attributes:
        source: Path inside the upstream repository.
        name: File name in the cache.
        sha256: Expected digest.
        size: Expected size in bytes.
    """

    source: str
    name: str
    sha256: str
    size: int


class ModelArtifactDto(FrozenObject):
    """An immutable model artifact.

    Attributes:
        model: Model name.
        repository: Upstream repository.
        revision: Upstream commit the files are taken from (never a branch or alias).
        licence: Licence of the model.
        quantization: `none` for the fp32 export.
        dimensions: Vector size.
        files: Every file, the model first and the tokenizer second.
    """

    model: str
    repository: str
    revision: str
    licence: str
    quantization: str
    dimensions: int
    files: tuple[ArtifactFileDto, ...]

    @property
    def model_file(self) -> ArtifactFileDto:
        """The ONNX file."""
        return self.files[0]

    @property
    def tokenizer_file(self) -> ArtifactFileDto:
        """The tokenizer file."""
        return self.files[1]

    @property
    def total_size(self) -> int:
        """Bytes of every file."""
        return sum(file.size for file in self.files)

    def profile(self) -> EmbeddingProfile:
        """The embedding profile this artifact defines; computed without touching the cache."""
        return EmbeddingProfile(
            model=self.model,
            artifact_revision=self.revision,
            artifact_sha256=self.model_file.sha256,
            tokenizer_sha256=self.tokenizer_file.sha256,
            runtime=RUNTIME,
            quantization=self.quantization,
            dimensions=self.dimensions,
            similarity="cosine",
            query_instruction=QUERY_INSTRUCTION,
            chunk_policy=CHUNK_POLICY_VERSION,
            query_policy=QUERY_POLICY_VERSION,
        )


BGE_SMALL_EN_V15: Final[ModelArtifactDto] = ModelArtifactDto(
    model="BAAI/bge-small-en-v1.5",
    repository="BAAI/bge-small-en-v1.5",
    revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    licence="MIT",
    quantization="none",
    dimensions=384,
    files=(
        ArtifactFileDto(
            source="onnx/model.onnx",
            name="model.onnx",
            sha256="828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
            size=133_093_490,
        ),
        ArtifactFileDto(
            source="tokenizer.json",
            name="tokenizer.json",
            sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
            size=711_396,
        ),
        ArtifactFileDto(
            source="config.json",
            name="config.json",
            sha256="094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750",
            size=743,
        ),
        ArtifactFileDto(
            source="special_tokens_map.json",
            name="special_tokens_map.json",
            sha256="b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
            size=125,
        ),
        ArtifactFileDto(
            source="tokenizer_config.json",
            name="tokenizer_config.json",
            sha256="9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3",
            size=366,
        ),
    ),
)
"""The pinned default: the official fp32 ONNX export at a fixed commit (D30: 384 dims)."""


class PreparedModelDto(FrozenObject):
    """What `prepare` (or a check of the cache) reports.

    Attributes:
        model: Model name.
        revision: Upstream revision.
        licence: Licence.
        directory: Where the files are.
        size_bytes: Bytes of every file.
        downloaded: Whether this call downloaded the files.
        files: File name to SHA-256.
    """

    model: str
    revision: str
    licence: str
    directory: str
    size_bytes: int
    downloaded: bool
    files: dict[str, str]


class ModelCache:
    """The cache directory of one artifact: `<root>/<model>/<revision>/`.

    Args:
        root: `NOESIS_RETRIEVAL_MODEL_CACHE_DIR`, else `$XDG_CACHE_HOME/noesis/models`.
        artifact: The pinned artifact.
    """

    def __init__(self, root: Path, artifact: ModelArtifactDto = BGE_SMALL_EN_V15) -> None:
        self._root: Path = root
        self._artifact: ModelArtifactDto = artifact

    @property
    def artifact(self) -> ModelArtifactDto:
        """The pinned artifact."""
        return self._artifact

    @property
    def directory(self) -> Path:
        """Where the prepared files live."""
        return self._root / self._artifact.model.replace("/", "--") / self._artifact.revision

    def path_of(self, name: str) -> Path:
        """The cached path of one file."""
        return self.directory / name

    def is_prepared(self) -> bool:
        """A cheap check (manifest and sizes, no hashing): safe for `index status`."""
        try:
            self._check(hash_files=False)
        except ModelCacheError:
            return False
        return True

    def verify(self) -> PreparedModelDto:
        """Check the manifest, sizes and digests of every file.

        Raises:
            ModelCacheError: Missing, incomplete or corrupt.
        """
        self._check(hash_files=True)
        return self._report(downloaded=False)

    def prepare(self, fetch: Fetch) -> PreparedModelDto:
        """Download, verify and atomically complete the cache; a no-op when already verified.

        Raises:
            ModelCacheError: A file failed its size or digest check (nothing is kept).
        """
        try:
            return self.verify()
        except ModelCacheError:
            pass
        self._root.mkdir(parents=True, exist_ok=True)
        staging: Path = Path(tempfile.mkdtemp(prefix=".prepare-", dir=self._root))
        try:
            for file in self._artifact.files:
                target: Path = staging / file.name
                fetch(self._url(file), target)
                _verify_file(target, file, hash_file=True)
            (staging / MANIFEST_NAME).write_text(
                json.dumps(self._manifest(), sort_keys=True, indent=2), encoding="utf-8"
            )
            self.directory.parent.mkdir(parents=True, exist_ok=True)
            if self.directory.exists():
                shutil.rmtree(self.directory)  # an incomplete or corrupt earlier copy
            staging.replace(self.directory)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return self._report(downloaded=True)

    def _url(self, file: ArtifactFileDto) -> str:
        return (
            f"{DOWNLOAD_BASE}/{self._artifact.repository}/resolve/"
            f"{self._artifact.revision}/{file.source}"
        )

    def _manifest(self) -> dict[str, object]:
        return {
            "model": self._artifact.model,
            "repository": self._artifact.repository,
            "revision": self._artifact.revision,
            "files": {file.name: file.sha256 for file in self._artifact.files},
        }

    def _check(self, *, hash_files: bool) -> None:
        manifest_path: Path = self.directory / MANIFEST_NAME
        try:
            manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ModelCacheError(
                f"the model {self._artifact.model} is not prepared at {self.directory}"
            ) from error
        if manifest != self._manifest():
            raise ModelCacheError(f"the prepared model at {self.directory} is another artifact")
        for file in self._artifact.files:
            _verify_file(self.path_of(file.name), file, hash_file=hash_files)

    def _report(self, *, downloaded: bool) -> PreparedModelDto:
        return PreparedModelDto(
            model=self._artifact.model,
            revision=self._artifact.revision,
            licence=self._artifact.licence,
            directory=str(self.directory),
            size_bytes=self._artifact.total_size,
            downloaded=downloaded,
            files={file.name: file.sha256 for file in self._artifact.files},
        )


def _verify_file(path: Path, file: ArtifactFileDto, *, hash_file: bool) -> None:
    try:
        size: int = path.stat().st_size
    except OSError as error:
        raise ModelCacheError(f"{file.name} is missing from the model cache") from error
    if size != file.size:
        raise ModelCacheError(f"{file.name} has {size} bytes, expected {file.size}")
    if hash_file and _sha256(path) != file.sha256:
        raise ModelCacheError(f"{file.name} does not match its pinned SHA-256")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
