"""`INoteReadRepository` that scans Markdown files under the vault folder.

A note is any `.md` file with a valid `noesis:` block, wherever it sits; every other file
(indexes, attachments' notes, plain documents) is not a note and never shows up.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

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
from noesis.exceptions import NoteStorageError
from noesis.shared_kernel.enums import SearchEngineEnum

from .mappers import NoteMapper
from .note_paths import checked_note_path

TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9]{3,}")
TITLE_WEIGHT: int = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class _IndexedNote:
    summary: NoteSummaryDto
    text: str


class FilesystemNoteReadRepositoryAdapter(INoteReadRepository):
    """Reads every note file on each query; fine for personal vaults of thousands of notes."""

    def __init__(self, vault_dir: Path, mapper: NoteMapper) -> None:
        self._vault_dir: Path = vault_dir
        self._mapper: NoteMapper = mapper

    def _notes(self, scope: NoteScope | None) -> Iterator[_IndexedNote]:
        if not self._vault_dir.is_dir():
            return
        for path in sorted(self._vault_dir.rglob("*.md")):
            relative: Path = path.relative_to(self._vault_dir)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            try:
                text: str = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue  # unreadable files are not notes
            summary: NoteSummaryDto | None = self._mapper.to_summary(relative.as_posix(), text)
            if summary is None or (scope is not None and summary.scope != scope.value):
                continue  # not a noesis note, or another scope
            yield _IndexedNote(summary=summary, text=text.lower())

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Notes ranked by how often the query's words occur (title words count triple)."""
        tokens: set[str] = set(TOKEN_PATTERN.findall(text.lower()))
        if not tokens:
            return self._result([])
        scored: list[tuple[int, str, NoteSummaryDto]] = []
        for note in self._notes(scope):
            title: str = note.summary.title.lower()
            score: int = sum(
                note.text.count(token) + TITLE_WEIGHT * title.count(token) for token in tokens
            )
            if score:
                scored.append((-score, note.summary.path, note.summary))
        return self._result([summary for _, _, summary in sorted(scored)[:limit]])

    @staticmethod
    def _result(notes: list[NoteSummaryDto]) -> NoteSearchResultDto:
        return NoteSearchResultDto(notes=tuple(notes), backend=SearchEngineEnum.FILESYSTEM)

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every note of `scope`, optionally only one origin, sorted by path."""
        return [
            note.summary
            for note in self._notes(scope)
            if origin is None or note.summary.origin == origin.value
        ]

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """The notes of `scope` and `kind`, sorted by path."""
        return [note.summary for note in self._notes(scope) if note.summary.kind == kind.value]

    async def find_by_id(self, note_id: NoteId) -> NoteSummaryDto | None:
        """The note with this id, wherever its file is."""
        return next(
            (note.summary for note in self._notes(None) if note.summary.id == note_id.value), None
        )

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """The note's file, refused when it escapes the vault or is not a note of `scope`."""
        relative: str = checked_note_path(path)
        file: Path = (self._vault_dir / relative).resolve()
        if not file.is_relative_to(self._vault_dir.resolve()):
            raise NoteStorageError(f"Refusing to read {path!r}: outside the vault.", {"path": path})
        try:
            text: str = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise NoteStorageError(
                f"Cannot read the note {relative}: {error}", {"path": relative}
            ) from error
        note: NoteContentDto | None = self._mapper.to_content(relative, text)
        if note is None or (scope is not None and note.scope != scope.value):
            raise NoteStorageError(
                f"Refusing to read {path!r}: not a note of the allowed scope.",
                {"path": path, "scope": scope.value if scope else None},
            )
        return note
