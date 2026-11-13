"""`INoteReadRepository` over a vectra collection: semantic search, file-backed lookups."""

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
)
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
)
from noesis.bounded_context.notes.infrastructure.outbound.vectra import (
    VectraCliClient,
    VectraClientError,
    VectraHit,
)
from noesis.exceptions import NoteStorageError
from noesis.shared_kernel.enums import SearchEngineEnum

OVERFETCH: int = 3


class VectraNoteReadRepositoryAdapter(INoteReadRepository):
    """Searches a vectra collection by meaning; everything else reads the collection's folder.

    Vectra stores chunks, not notes: it answers with document paths relative to the collection
    root. Each hit is resolved through `files` (a reader of that same folder), which also
    applies the scope from the note's frontmatter. Hits are over-fetched so a scope filter
    still fills `limit`.

    Args:
        client: The vectra client.
        collection: Collection name.
        files: Reader of the folder the collection indexes.
    """

    def __init__(
        self, *, client: VectraCliClient, collection: str, files: INoteReadRepository
    ) -> None:
        self._client: VectraCliClient = client
        self._collection: str = collection
        self._files: INoteReadRepository = files

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Notes closest in meaning to `text`, best first.

        Raises:
            NoteStorageError: vectra could not answer.
        """
        if not text.strip() or limit < 1:
            return NoteSearchResultDto(notes=(), backend=SearchEngineEnum.VECTRA)
        try:
            hits: tuple[VectraHit, ...] = await self._client.search(
                self._collection, text, limit * OVERFETCH
            )
        except VectraClientError as error:
            raise NoteStorageError(
                f"vectra could not search collection {self._collection!r}: {error}",
                {"collection": self._collection},
                next_steps=[
                    f"Run `vectra sync {self._collection} <folder>` and check `vectra config`."
                ],
            ) from error
        by_path: dict[str, NoteSummaryDto] = {
            note.path: note for note in await self._files.list_notes(scope=scope, origin=None)
        }
        notes: list[NoteSummaryDto] = [by_path[hit.path] for hit in hits if hit.path in by_path]
        return NoteSearchResultDto(notes=tuple(notes[:limit]), backend=SearchEngineEnum.VECTRA)

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every note of the collection's folder."""
        return await self._files.list_notes(scope=scope, origin=origin)

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """The notes of `scope` and `kind` in the collection's folder."""
        return await self._files.find_active(scope, kind)

    async def find_by_id(
        self, note_id: NoteId, *, scope: NoteScope | None
    ) -> NoteSummaryDto | None:
        """The note with this id in the collection's folder."""
        return await self._files.find_by_id(note_id, scope=scope)

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """One note of the collection's folder, in full."""
        return await self._files.read_note(path, scope=scope)
