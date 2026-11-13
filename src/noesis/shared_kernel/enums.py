"""Enumerations shared by settings, bounded contexts and the interfaces."""

from enum import StrEnum


class SearchEngineEnum(StrEnum):
    """Which engine answers a note search.

    FILESYSTEM: scans the vault's Markdown files. OBSIDIAN_MCP: asks Obsidian's MCP server.
    VECTRA: semantic search in a vectra collection of the vault.
    """

    FILESYSTEM = "filesystem"
    OBSIDIAN_MCP = "obsidian-mcp"
    VECTRA = "vectra"


class WriterBackendEnum(StrEnum):
    """Where `notes curate` stores the notes.

    FILESYSTEM: Markdown files under the vault folder (a plain folder, an Obsidian vault, an NFS
    mount). MCP: Obsidian's MCP server (`vault_write`), for a vault noesis cannot reach as files.
    VECTRA: Markdown files under the vault folder, then synced into a vectra collection.
    """

    FILESYSTEM = "filesystem"
    MCP = "mcp"
    VECTRA = "vectra"
