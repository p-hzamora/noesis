"""`INoteRepository` over Markdown files in a vault folder."""

from pathlib import Path

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.repositories import INoteRepository
from noesis.bounded_context.notes.domain.value_objects import NotePath
from noesis.exceptions import (
    NoteStorageError,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import write_text_atomic

from .mappers import NoteMapper


class FilesystemNoteRepositoryAdapter(INoteRepository):
    """Reads notes from `<vault>/<path>`; stages writes until `flush`."""

    def __init__(self, vault_dir: Path, mapper: NoteMapper) -> None:
        self._vault_dir: Path = vault_dir
        self._mapper: NoteMapper = mapper
        self._staged: dict[str, Note] = {}

    def _file(self, path: NotePath) -> Path:
        return self._vault_dir / path.value

    async def get(self, path: NotePath) -> Note | None:
        """The note at `path`, preferring a staged version.

        Raises:
            NoteStorageError: The file exists but cannot be read.
        """
        if path.value in self._staged:
            return self._staged[path.value]
        file: Path = self._file(path)
        if not file.is_file():
            return None
        try:
            text: str = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise NoteStorageError(f"Cannot read {file}: {error}", {"path": str(file)}) from error
        return self._mapper.to_entity(text, path)

    async def exists(self, path: NotePath) -> bool:
        """Whether a file or a staged note occupies `path`."""
        return path.value in self._staged or self._file(path).exists()

    async def save(self, note: Note) -> None:
        """Stage `note`; nothing touches the disk until `flush`."""
        self._staged[note.path.value] = note

    def flush(self) -> None:
        """Write every staged note atomically, then clear the stage.

        Raises:
            NoteStorageError: A file could not be written.
        """
        for path, note in self._staged.items():
            file: Path = self._vault_dir / path
            try:
                existing: str | None = file.read_text(encoding="utf-8") if file.is_file() else None
                write_text_atomic(file, self._mapper.to_markdown(note, existing))
            except (OSError, UnicodeDecodeError) as error:
                raise NoteStorageError(
                    f"Cannot write {file}: {error}",
                    {"path": str(file)},
                    next_steps=[
                        "Check that NOESIS_VAULT_DIR exists and is writable (`noesis doctor`)."
                    ],
                ) from error
        self._staged.clear()

    def discard(self) -> None:
        """Forget staged notes without writing them."""
        self._staged.clear()
