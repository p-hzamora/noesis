"""`INoteRepository` over Markdown files in a vault folder."""

from pathlib import Path

from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.repositories import INoteRepository
from noesis.bounded_context.knowledge.domain.value_objects import NoteLocation
from noesis.exceptions import (
    NoteStorageError,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import write_text_atomic

from .mappers import NoteMapper


class FilesystemNoteRepositoryAdapter(INoteRepository):
    """Reads notes from `<vault>/<location>`; stages writes until `flush`."""

    def __init__(self, vault_dir: Path, mapper: NoteMapper) -> None:
        self._vault_dir: Path = vault_dir
        self._mapper: NoteMapper = mapper
        self._staged: dict[Path, Note] = {}

    def _path(self, location: NoteLocation) -> Path:
        return self._vault_dir / location.relative_path

    async def get(self, location: NoteLocation) -> Note | None:
        """The note at `location`, preferring a staged version.

        Raises:
            NoteStorageError: The file exists but cannot be read.
        """
        path: Path = self._path(location)
        if path in self._staged:
            return self._staged[path]
        if not path.is_file():
            return None
        try:
            text: str = path.read_text(encoding="utf-8")
        except OSError as error:
            raise NoteStorageError(f"Cannot read {path}: {error}", {"path": str(path)}) from error
        return self._mapper.to_entity(text, location)

    async def save(self, note: Note) -> None:
        """Stage `note`; nothing touches the disk until `flush`."""
        self._staged[self._path(note.location)] = note

    def flush(self) -> None:
        """Write every staged note atomically, then clear the stage.

        Raises:
            NoteStorageError: A file could not be written.
        """
        for path, note in self._staged.items():
            try:
                write_text_atomic(path, self._mapper.to_markdown(note))
            except OSError as error:
                raise NoteStorageError(
                    f"Cannot write {path}: {error}",
                    {"path": str(path)},
                    next_steps=[
                        "Check that NOESIS_VAULT_DIR exists and is writable (`noesis doctor`)."
                    ],
                ) from error
        self._staged.clear()

    def discard(self) -> None:
        """Forget staged notes without writing them."""
        self._staged.clear()
