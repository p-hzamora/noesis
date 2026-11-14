"""Note storage and reading: files (any folder, NFS, an Obsidian vault) and vectra collections."""

from .fallback_note_read_repository_adapter import FallbackNoteReadRepositoryAdapter
from .filesystem_note_read_repository_adapter import FilesystemNoteReadRepositoryAdapter
from .filesystem_note_repository_adapter import FilesystemNoteRepositoryAdapter
from .filesystem_notes_unit_of_work_adapter import FilesystemNotesUnitOfWorkAdapter
from .multi_source_note_read_repository_adapter import (
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from .vectra_note_read_repository_adapter import VectraNoteReadRepositoryAdapter
from .vectra_note_repository_adapter import VectraNoteRepositoryAdapter
from .vectra_notes_unit_of_work_adapter import VectraNotesUnitOfWorkAdapter

__all__ = [
    "FallbackNoteReadRepositoryAdapter",
    "FilesystemNotesUnitOfWorkAdapter",
    "FilesystemNoteReadRepositoryAdapter",
    "FilesystemNoteRepositoryAdapter",
    "MultiSourceNoteReadRepositoryAdapter",
    "SourceReader",
    "VectraNoteReadRepositoryAdapter",
    "VectraNoteRepositoryAdapter",
    "VectraNotesUnitOfWorkAdapter",
]
