"""Settings for where notes are stored and how they are searched."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings

DEFAULT_OBSIDIAN_MCP_URL: str = "http://127.0.0.1:27123/mcp/"


class SearchBackendEnum(StrEnum):
    """Where `knowledge search` (and the curator's related-notes lookup) reads from."""

    FILESYSTEM = "filesystem"
    OBSIDIAN_MCP = "obsidian-mcp"


class KnowledgeSettings(AppBaseSettings):
    """Storage and search settings.

    Attributes:
        vault_dir: Folder that holds the notes: an Obsidian vault, a plain folder, or an
            NFS mount (`NOESIS_VAULT_DIR`). None until the user configures it.
        search_backend: `filesystem` scans the Markdown files (default); `obsidian-mcp` asks
            Obsidian's MCP server and falls back to files when it is unreachable
            (`NOESIS_SEARCH_BACKEND`).
        obsidian_mcp_url: Obsidian MCP endpoint (`NOESIS_OBSIDIAN_MCP_URL`).
        obsidian_mcp_token: Token the MCP server requires, if any (`NOESIS_OBSIDIAN_MCP_TOKEN`);
            a secret: masked in `config show`, never logged.
        obsidian_mcp_timeout_seconds: Connect and per-call time limit; a closed Obsidian must
            not stall a search (`NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    vault_dir: Path | None = None
    search_backend: SearchBackendEnum = SearchBackendEnum.FILESYSTEM
    obsidian_mcp_url: str = DEFAULT_OBSIDIAN_MCP_URL
    obsidian_mcp_token: SecretStr | None = None
    obsidian_mcp_timeout_seconds: float = Field(default=5.0, gt=0)

    @field_validator("vault_dir", mode="after")
    @classmethod
    def _expand_vault_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None
