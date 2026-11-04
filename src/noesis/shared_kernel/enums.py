"""Enumerations shared by settings, bounded contexts and the interfaces."""

from enum import StrEnum


class SearchEngineEnum(StrEnum):
    """Which engine answers a note search.

    FILESYSTEM: scans the vault's Markdown files. OBSIDIAN_MCP: asks Obsidian's MCP server.
    """

    FILESYSTEM = "filesystem"
    OBSIDIAN_MCP = "obsidian-mcp"


class WriterBackendEnum(StrEnum):
    """Where `knowledge curate` stores the notes.

    FILESYSTEM: Markdown files under the vault folder (a plain folder, an Obsidian vault, an NFS
    mount). MCP: Obsidian's MCP server (`vault_write`), for a vault noesis cannot reach as files.
    """

    FILESYSTEM = "filesystem"
    MCP = "mcp"
