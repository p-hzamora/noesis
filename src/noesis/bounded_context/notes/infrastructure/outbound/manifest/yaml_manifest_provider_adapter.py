"""`IManifestProvider` that merges the packaged default with the user's `noesis.yaml`."""

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from noesis.bounded_context.notes.application.ports.manifest import IManifestProvider
from noesis.bounded_context.notes.application.services.manifest import (
    Manifest,
    merge_manifest_data,
)
from noesis.exceptions import InvalidManifestError

RESOURCE_PACKAGE: str = "noesis.bounded_context.notes.infrastructure.outbound.manifest"
DEFAULT_RESOURCE: str = "noesis.yaml"
USER_MANIFEST: str = "noesis.yaml"


class YamlManifestProviderAdapter(IManifestProvider):
    """The only loader of the manifest format: one schema for the default and the user file.

    The user file is `noesis.yaml` at the root of the source (the vault folder); without a
    vault, or without the file, the default alone is the manifest.
    """

    def __init__(self, source_root: Path | None) -> None:
        self._source_root: Path | None = source_root

    async def load(self) -> Manifest:
        """The effective manifest, see `load_now`."""
        return self.load_now()

    def load_now(self) -> Manifest:
        """The effective manifest (nothing here awaits, so wiring code may call it directly).

        Raises:
            InvalidManifestError: The user file cannot be read, is not YAML, or breaks a rule.
        """
        default: dict[str, Any] = self._read_default()
        user: dict[str, Any] = self._read_user()
        try:
            return Manifest.model_validate(merge_manifest_data(default, user))
        except ValidationError as error:
            first = error.errors()[0]
            where: str = ".".join(str(part) for part in first["loc"])
            raise InvalidManifestError(
                f"Invalid manifest: {where}: {first['msg']}"
                if where
                else f"Invalid manifest: {first['msg']}",
                {
                    "errors": [
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
                    ]
                },
                next_steps=[f"Fix `{USER_MANIFEST}` at the root of your vault."],
            ) from error

    @staticmethod
    def _read_default() -> dict[str, Any]:
        text: str = files(RESOURCE_PACKAGE).joinpath(DEFAULT_RESOURCE).read_text(encoding="utf-8")
        loaded: object = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}

    def _read_user(self) -> dict[str, Any]:
        if self._source_root is None:
            return {}
        path: Path = self._source_root / USER_MANIFEST
        if not path.is_file():
            return {}
        try:
            loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            raise InvalidManifestError(
                f"Cannot read the manifest {path}: {error}",
                {"path": str(path)},
                next_steps=[f"Fix or remove {path}."],
            ) from error
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise InvalidManifestError(
                f"The manifest {path} must be a YAML mapping.", {"path": str(path)}
            )
        return loaded
