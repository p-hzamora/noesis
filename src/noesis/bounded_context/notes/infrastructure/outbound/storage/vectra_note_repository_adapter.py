"""`INoteRepository` that writes notes as files and then syncs them into a vectra collection."""

from collections.abc import Callable
from pathlib import Path

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.repositories import INoteRepository
from noesis.bounded_context.notes.domain.value_objects import NotePath
from noesis.bounded_context.notes.infrastructure.outbound.vectra import (
    VectraCliClient,
    VectraClientError,
)

from .filesystem_note_repository_adapter import FilesystemNoteRepositoryAdapter


class VectraNoteRepositoryAdapter(INoteRepository):
    """Files are the record, the collection is their index.

    Vectra indexes a folder; it cannot hold a note by itself. So `get`, `exists` and `save`
    work on the collection's folder, and `flush` writes the files and then runs `vectra sync`.
    A failed sync does not undo the write: the files are durable and the next sync catches up,
    so it is reported through `on_sync_failure` instead of raised.

    Args:
        files: Repository of the folder the collection indexes.
        client: The vectra client.
        collection: Collection name.
        root: The folder the collection indexes.
        on_sync_failure: Called with the error when a sync fails.
    """

    def __init__(
        self,
        *,
        files: FilesystemNoteRepositoryAdapter,
        client: VectraCliClient,
        collection: str,
        root: Path,
        on_sync_failure: Callable[[VectraClientError], None] = lambda _error: None,
    ) -> None:
        self._files: FilesystemNoteRepositoryAdapter = files
        self._client: VectraCliClient = client
        self._collection: str = collection
        self._root: Path = root
        self._on_sync_failure: Callable[[VectraClientError], None] = on_sync_failure

    async def get(self, path: NotePath) -> Note | None:
        """The note at `path`, preferring a staged version."""
        return await self._files.get(path)

    async def exists(self, path: NotePath) -> bool:
        """Whether a file or a staged note occupies `path`."""
        return await self._files.exists(path)

    async def save(self, note: Note) -> None:
        """Stage `note`; nothing is written or indexed until `flush`."""
        await self._files.save(note)

    async def flush(self) -> None:
        """Write the staged notes, then index them.

        Raises:
            NoteStorageError: A file could not be written (nothing is indexed then).
        """
        self._files.flush()
        try:
            await self._client.sync(self._collection, self._root)
        except VectraClientError as error:
            self._on_sync_failure(error)

    def discard(self) -> None:
        """Forget staged notes without writing them."""
        self._files.discard()
