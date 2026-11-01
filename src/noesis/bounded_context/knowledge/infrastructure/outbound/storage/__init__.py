"""Filesystem storage of notes: works for an Obsidian vault, a plain folder, or NFS."""

from noesis.bounded_context.knowledge.infrastructure.outbound.storage.filesystem_knowledge_unit_of_work_adapter import (
    FilesystemKnowledgeUnitOfWorkAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.filesystem_note_read_repository_adapter import (
    FilesystemNoteReadRepositoryAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.filesystem_note_repository_adapter import (
    FilesystemNoteRepositoryAdapter,
)

__all__ = [
    "FilesystemKnowledgeUnitOfWorkAdapter",
    "FilesystemNoteReadRepositoryAdapter",
    "FilesystemNoteRepositoryAdapter",
]
