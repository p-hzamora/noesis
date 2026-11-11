"""`INoteReadRepository` that fans a query out over every source the manifest declares."""

from collections.abc import Sequence
from dataclasses import dataclass

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
    VectorHitDto,
)
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.vector import IVectorSearch
from noesis.bounded_context.notes.application.services.manifest import (
    SourceRoleEnum,
    SourceSpec,
)
from noesis.bounded_context.notes.application.services.recall import RankedNotes, fuse_rankings
from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
)
from noesis.exceptions import NoteStorageError


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceReader:
    """A declared source and the repository that reads it."""

    spec: SourceSpec
    repository: INoteReadRepository

    def __init__(self, spec: SourceSpec, repository: INoteReadRepository) -> None:
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "repository", repository)

    @property
    def primary(self) -> bool:
        return self.spec.role is SourceRoleEnum.PRIMARY


class MultiSourceNoteReadRepositoryAdapter(INoteReadRepository):
    """Merges the sources' answers by note id; the primary's copy of a note wins.

    Args:
        readers: The sources to read.
        index: An optional vector index derived from the primary; its hits are resolved to notes
            through the readers.
    """

    def __init__(
        self, readers: Sequence[SourceReader], *, index: IVectorSearch | None = None
    ) -> None:
        self._readers: list[SourceReader] = sorted(readers, key=lambda reader: not reader.primary)
        self._index: IVectorSearch | None = index

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Fused ranking of every source's search (and of the index, when there is one)."""
        rankings: list[RankedNotes] = []
        backend = None
        for reader in self._readers:
            answer: NoteSearchResultDto = await reader.repository.search(
                text, scope=scope, limit=limit
            )
            backend = backend or answer.backend
            rankings.append(RankedNotes(primary=reader.primary, notes=answer.notes))
        if self._index is not None:
            rankings.append(
                RankedNotes(primary=False, notes=await self._indexed(text, scope, limit))
            )
        if backend is None:
            raise NoteStorageError("No source is configured to search.", {})
        return NoteSearchResultDto(
            notes=tuple(fuse_rankings(rankings, limit=limit)), backend=backend
        )

    async def _indexed(
        self, text: str, scope: NoteScope | None, limit: int
    ) -> list[NoteSummaryDto]:
        assert self._index is not None  # noqa: S101 - narrowed by the caller
        notes: list[NoteSummaryDto] = []
        hits: tuple[VectorHitDto, ...] = await self._index.search(text, limit)
        for hit in sorted(hits, key=lambda item: item.rank):
            found: NoteSummaryDto | None = await self.find_by_id(NoteId(value=hit.id))
            if found is not None and (scope is None or found.scope == scope.value):
                notes.append(found)
        return notes

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every source's notes, one per id, primary first."""
        merged: dict[str, NoteSummaryDto] = {}
        for reader in self._readers:
            for note in await reader.repository.list_notes(scope=scope, origin=origin):
                merged.setdefault(note.id, note)
        return list(merged.values())

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """Every source's notes of `scope` and `kind`, one per id, primary first."""
        merged: dict[str, NoteSummaryDto] = {}
        for reader in self._readers:
            for note in await reader.repository.find_active(scope, kind):
                merged.setdefault(note.id, note)
        return list(merged.values())

    async def find_by_id(self, note_id: NoteId) -> NoteSummaryDto | None:
        """The first source (primary first) that has the note."""
        for reader in self._readers:
            found: NoteSummaryDto | None = await reader.repository.find_by_id(note_id)
            if found is not None:
                return found
        return None

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """The note from the first source that can read it (primary first)."""
        failure: NoteStorageError | None = None
        for reader in self._readers:
            try:
                return await reader.repository.read_note(path, scope=scope)
            except NoteStorageError as error:
                failure = failure or error
        raise failure or NoteStorageError("No source is configured to read.", {"path": path})
