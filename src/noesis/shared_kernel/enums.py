"""Enumerations shared by settings, bounded contexts and the interfaces."""

from enum import StrEnum


class SearchEngineEnum(StrEnum):
    """Which engine answers a note search.

    FILESYSTEM: scans the vault's Markdown files.
    VECTRA: semantic search in a vectra collection of the vault.
    """

    FILESYSTEM = "filesystem"
    VECTRA = "vectra"


class WriterBackendEnum(StrEnum):
    """Where `notes curate` stores the notes.

    FILESYSTEM: Markdown files under the vault folder (a plain folder, an Obsidian vault, an NFS
    mount).
    VECTRA: Markdown files under the vault folder, then synced into a vectra collection.
    """

    FILESYSTEM = "filesystem"
    VECTRA = "vectra"
