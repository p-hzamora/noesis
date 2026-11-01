"""Settings for where notes are stored."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class KnowledgeSettings(AppBaseSettings):
    """Storage settings.

    Attributes:
        vault_dir: Folder that holds the notes: an Obsidian vault, a plain folder, or an
            NFS mount (`NOESIS_VAULT_DIR`). None until the user configures it.
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    vault_dir: Path | None = None

    @field_validator("vault_dir", mode="after")
    @classmethod
    def _expand_vault_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None
