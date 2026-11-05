"""Settings for where notes are stored and how they are searched."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from noesis.shared_kernel.enums import SearchEngineEnum, WriterBackendEnum

from .base_settings import AppBaseSettings

DEFAULT_OBSIDIAN_MCP_URL: str = "http://127.0.0.1:27123/mcp/"


class NotesSettings(AppBaseSettings):
    """Storage and search settings.

    Attributes:
        vault_dir: Folder that holds the notes: an Obsidian vault, a plain folder, or an
            NFS mount (`NOESIS_VAULT_DIR`). None until the user configures it.
        search_backend: `filesystem` scans the Markdown files (default); `obsidian-mcp` asks
            Obsidian's MCP server and falls back to files when it is unreachable
            (`NOESIS_SEARCH_BACKEND`).
        writer_backend: `filesystem` writes the notes as files under `vault_dir` (default; point
            it at an NFS mount to write there); `mcp` stores them through Obsidian's MCP server,
            using the `obsidian_mcp_*` settings (`NOESIS_WRITER_BACKEND`). Reads follow
            `search_backend`, independent of the writer.
        obsidian_mcp_url: Obsidian MCP endpoint, for search and for the `mcp` writer
            (`NOESIS_OBSIDIAN_MCP_URL`).
        obsidian_mcp_token: Token the MCP server requires, if any (`NOESIS_OBSIDIAN_MCP_TOKEN`);
            a secret: masked in `config show`, never logged.
        obsidian_mcp_timeout_seconds: Connect and per-call time limit; a closed Obsidian must
            not stall a search (`NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    vault_dir: Path | None = None
    writer_backend: WriterBackendEnum = WriterBackendEnum.FILESYSTEM
    search_backend: SearchEngineEnum = SearchEngineEnum.FILESYSTEM
    obsidian_mcp_url: str = DEFAULT_OBSIDIAN_MCP_URL
    obsidian_mcp_token: SecretStr | None = None
    obsidian_mcp_timeout_seconds: float = Field(default=5.0, gt=0)

    @field_validator("vault_dir", mode="after")
    @classmethod
    def _expand_vault_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None
