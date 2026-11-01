"""`INoteReadRepository` that scans Markdown files under the vault folder."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.knowledge.application.dtos import NoteSummaryDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.knowledge.domain.value_objects import (
    NoteArea,
    NoteLocation,
    NoteOriginEnum,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.mappers import (
    NoteMapper,
    ParsedMarkdown,
)
from noesis.exceptions import DomainException

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

    def _notes(self, area: NoteArea | None) -> Iterator[_IndexedNote]:
        root: Path = self._vault_dir / area.value if area else self._vault_dir
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*.md")):
            relative: Path = path.relative_to(self._vault_dir)
            if any(part.startswith(".") for part in relative.parts):
                continue
            try:
                location: NoteLocation = NoteLocation.parse(relative.as_posix())
                text: str = path.read_text(encoding="utf-8")
            except DomainException, OSError:
                continue  # index files, attachments notes and unreadable files are not notes
            parsed: ParsedMarkdown = self._mapper.parse(text)
            updated: object = parsed.frontmatter.get("updated") or parsed.frontmatter.get("date")
            yield _IndexedNote(
                summary=NoteSummaryDto(
                    path=location.relative_path,
                    title=parsed.title or location.slug.value,
                    kind=location.kind.value,
                    origin=location.origin.value,
                    updated=str(updated) if updated else None,
                    snippet=self._mapper.snippet(parsed),
                ),
                text=text.lower(),
            )

    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> list[NoteSummaryDto]:
        """Notes ranked by how often the query's words occur (title words count triple)."""
        tokens: set[str] = set(TOKEN_PATTERN.findall(text.lower()))
        if not tokens:
            return []
        scored: list[tuple[int, str, NoteSummaryDto]] = []
        for note in self._notes(area):
            title: str = note.summary.title.lower()
            score: int = sum(
                note.text.count(token) + TITLE_WEIGHT * title.count(token) for token in tokens
            )
            if score:
                scored.append((-score, note.summary.path, note.summary))
        return [summary for _, _, summary in sorted(scored)[:limit]]

    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Every note under `area`, optionally only one origin, sorted by path."""
        return [
            note.summary
            for note in self._notes(area)
            if origin is None or note.summary.origin == origin.value
        ]
