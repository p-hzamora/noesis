"""Note storage and reading: files (any folder, NFS, an Obsidian vault) and Obsidian's MCP server."""

from .fallback_note_read_repository_adapter import FallbackNoteReadRepositoryAdapter
from .filesystem_knowledge_unit_of_work_adapter import FilesystemKnowledgeUnitOfWorkAdapter
from .filesystem_note_read_repository_adapter import FilesystemNoteReadRepositoryAdapter
from .filesystem_note_repository_adapter import FilesystemNoteRepositoryAdapter
from .mcp_knowledge_unit_of_work_adapter import McpKnowledgeUnitOfWorkAdapter
from .mcp_note_repository_adapter import McpNoteRepositoryAdapter
from .obsidian_mcp_note_read_repository_adapter import ObsidianMcpNoteReadRepositoryAdapter
from .unavailable_note_read_repository_adapter import UnavailableNoteReadRepositoryAdapter

__all__ = [
    "FallbackNoteReadRepositoryAdapter",
    "FilesystemKnowledgeUnitOfWorkAdapter",
    "FilesystemNoteReadRepositoryAdapter",
    "FilesystemNoteRepositoryAdapter",
    "McpKnowledgeUnitOfWorkAdapter",
    "McpNoteRepositoryAdapter",
    "ObsidianMcpNoteReadRepositoryAdapter",
    "UnavailableNoteReadRepositoryAdapter",
]
