"""Note storage and reading: files (any folder, NFS, an Obsidian vault) and Obsidian's MCP server."""

from .fallback_note_read_repository_adapter import FallbackNoteReadRepositoryAdapter
from .filesystem_note_read_repository_adapter import FilesystemNoteReadRepositoryAdapter
from .filesystem_note_repository_adapter import FilesystemNoteRepositoryAdapter
from .filesystem_notes_unit_of_work_adapter import FilesystemNotesUnitOfWorkAdapter
from .mcp_note_repository_adapter import McpNoteRepositoryAdapter
from .mcp_notes_unit_of_work_adapter import McpNotesUnitOfWorkAdapter
from .obsidian_mcp_note_read_repository_adapter import ObsidianMcpNoteReadRepositoryAdapter
from .unavailable_note_read_repository_adapter import UnavailableNoteReadRepositoryAdapter

__all__ = [
    "FallbackNoteReadRepositoryAdapter",
    "FilesystemNotesUnitOfWorkAdapter",
    "FilesystemNoteReadRepositoryAdapter",
    "FilesystemNoteRepositoryAdapter",
    "McpNotesUnitOfWorkAdapter",
    "McpNoteRepositoryAdapter",
    "ObsidianMcpNoteReadRepositoryAdapter",
    "UnavailableNoteReadRepositoryAdapter",
]
