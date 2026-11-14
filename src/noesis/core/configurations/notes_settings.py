"""Settings for where notes are stored and how they are searched."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from noesis.exceptions import RemovedBackendError
from noesis.shared_kernel.enums import SearchEngineEnum, WriterBackendEnum

from .base_settings import AppBaseSettings

REMOVED_SEARCH_BACKENDS: frozenset[str] = frozenset({"obsidian-mcp"})
REMOVED_WRITER_BACKENDS: frozenset[str] = frozenset({"mcp"})


class NotesSettings(AppBaseSettings):
    """Storage and search settings.

    Attributes:
        vault_dir: Folder that holds the notes: an Obsidian vault, a plain folder, or an
            NFS mount (`NOESIS_VAULT_DIR`). None until the user configures it.
        search_backend: `filesystem` scans the Markdown files (default); `vectra`
            searches `vectra_collection` by meaning and falls back to files when vectra fails
            (`NOESIS_SEARCH_BACKEND`). The removed value `obsidian-mcp` fails validation with
            `RemovedBackendError`.
        writer_backend: `filesystem` writes the notes as files under `vault_dir` (default; point
            it at an NFS mount to write there); `vectra` writes the files and then syncs them
            into `vectra_collection` (`NOESIS_WRITER_BACKEND`). Reads follow
            `search_backend`, independent of the writer. The removed value `mcp` fails
            validation with `RemovedBackendError`.
        vectra_bin: The `vectra` executable (`NOESIS_VECTRA_BIN`).
        vectra_collection: Collection of the whole vault for the `vectra` search and writer
            backends (`NOESIS_VECTRA_COLLECTION`); manifest `vector` sources use their own name.
        vectra_timeout_seconds: Time limit for one `vectra search`; a slow index must not stall
            recall, and one `vectra sync` (`NOESIS_VECTRA_TIMEOUT_SECONDS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    vault_dir: Path | None = None
    writer_backend: WriterBackendEnum = WriterBackendEnum.FILESYSTEM
    search_backend: SearchEngineEnum = SearchEngineEnum.FILESYSTEM
    vectra_bin: str = "vectra"
    vectra_collection: str = "noesis"
    vectra_timeout_seconds: float = Field(default=120.0, gt=0)

    @field_validator("vault_dir", mode="after")
    @classmethod
    def _expand_vault_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    @field_validator("search_backend", mode="before")
    @classmethod
    def _reject_removed_search_backend(cls, value: object) -> object:
        _reject_removed(value, REMOVED_SEARCH_BACKENDS, "NOESIS_SEARCH_BACKEND")
        return value

    @field_validator("writer_backend", mode="before")
    @classmethod
    def _reject_removed_writer_backend(cls, value: object) -> object:
        _reject_removed(value, REMOVED_WRITER_BACKENDS, "NOESIS_WRITER_BACKEND")
        return value


def _reject_removed(value: object, removed: frozenset[str], variable: str) -> None:
    """Fail with a typed error, before any I/O, when `value` names a removed backend."""
    if isinstance(value, str) and value.strip().lower() in removed:
        raise RemovedBackendError(
            f"{variable}={value!r} names a backend that noesis no longer ships.",
            {"variable": variable, "value": value},
            next_steps=[f"Set {variable}=filesystem (or vectra) in your .env file or environment."],
        )
