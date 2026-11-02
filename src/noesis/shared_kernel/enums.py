"""Enumerations shared by settings, bounded contexts and the interfaces."""

from enum import StrEnum


class SearchEngineEnum(StrEnum):
    """Which engine answers a note search.

    FILESYSTEM: scans the vault's Markdown files. OBSIDIAN_MCP: asks Obsidian's MCP server.
    """

    FILESYSTEM = "filesystem"
    OBSIDIAN_MCP = "obsidian-mcp"
