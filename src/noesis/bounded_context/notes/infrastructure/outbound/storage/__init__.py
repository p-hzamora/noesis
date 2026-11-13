"""Note storage and reading: files (any folder, NFS, an Obsidian vault), Obsidian's MCP server
and vectra collections."""

from .fallback_note_read_repository_adapter import FallbackNoteReadRepositoryAdapter
from .filesystem_note_read_repository_adapter import FilesystemNoteReadRepositoryAdapter
from .filesystem_note_repository_adapter import FilesystemNoteRepositoryAdapter
from .filesystem_notes_unit_of_work_adapter import FilesystemNotesUnitOfWorkAdapter
from .mcp_note_repository_adapter import McpNoteRepositoryAdapter
from .mcp_notes_unit_of_work_adapter import McpNotesUnitOfWorkAdapter
from .multi_source_note_read_repository_adapter import (
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from .obsidian_mcp_note_read_repository_adapter import ObsidianMcpNoteReadRepositoryAdapter
from .unavailable_note_read_repository_adapter import UnavailableNoteReadRepositoryAdapter
from .vectra_note_read_repository_adapter import VectraNoteReadRepositoryAdapter
from .vectra_note_repository_adapter import VectraNoteRepositoryAdapter
from .vectra_notes_unit_of_work_adapter import VectraNotesUnitOfWorkAdapter

__all__ = [
    "FallbackNoteReadRepositoryAdapter",
    "FilesystemNotesUnitOfWorkAdapter",
    "FilesystemNoteReadRepositoryAdapter",
    "FilesystemNoteRepositoryAdapter",
    "McpNotesUnitOfWorkAdapter",
    "MultiSourceNoteReadRepositoryAdapter",
    "McpNoteRepositoryAdapter",
    "ObsidianMcpNoteReadRepositoryAdapter",
    "SourceReader",
    "UnavailableNoteReadRepositoryAdapter",
    "VectraNoteReadRepositoryAdapter",
    "VectraNoteRepositoryAdapter",
    "VectraNotesUnitOfWorkAdapter",
]
