"""`INoteReadRepository` that searches through Obsidian's MCP server.

Obsidian indexes the whole vault (manual notes, topics, other know-how folders),
ranks by relevance and is always up to date, so a search is one MCP call plus one read per
hit instead of a scan of every file. Read-only: writes keep going through the filesystem.

Tools used (names and shapes of the `obsidian` MCP server):

* `search_simple {query}` -> a JSON list of hits with `filename` (vault-relative path) and
  an optional `score`. The score is negative and the LOWER the better (a note named after the
  query scores far below one that mentions it once), and the list comes worst first.
* `vault_read {path}` -> JSON with the file's `content`.
"""

from typing import Final

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
from noesis.exceptions import NoteStorageError, ObsidianMcpError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient, ObsidianMcpSession

from .mappers import NoteMapper
from .note_paths import checked_note_path

NOTE_SUFFIX: Final[str] = ".md"


def _hit_path(hit: JsonValue) -> str | None:
    """Vault-relative path of one `search_simple` hit, or None when it is not a note file."""
    raw: JsonValue = hit
    if isinstance(hit, dict):
        raw = hit.get("filename") or hit.get("path")
    if not isinstance(raw, str) or not raw.endswith(NOTE_SUFFIX):
        return None
    path: str = raw.lstrip("/")
    return None if any(part.startswith(".") for part in path.split("/")) else path


def _hit_score(hit: JsonValue) -> float:
    score: JsonValue = hit.get("score") if isinstance(hit, dict) else None
    return float(score) if isinstance(score, int | float) and not isinstance(score, bool) else 0.0


def _hits(answer: JsonValue) -> list[JsonValue]:
    if isinstance(answer, dict):
        answer = answer.get("results", answer.get("hits"))
    if not isinstance(answer, list):
        raise ObsidianMcpError("Obsidian MCP `search_simple` answered an unexpected shape.")
    return answer


class ObsidianMcpNoteReadRepositoryAdapter(INoteReadRepository):
    """Searches with Obsidian; listing stays on `listing` (the MCP route would be chatty).

    Raises `ObsidianMcpError` from `search` when Obsidian cannot answer; wrap it in
    `FallbackNoteReadRepositoryAdapter` to degrade to file search.
    """

    def __init__(
        self, client: ObsidianMcpClient, mapper: NoteMapper, *, listing: INoteReadRepository
    ) -> None:
        self._client: ObsidianMcpClient = client
        self._mapper: NoteMapper = mapper
        self._listing: INoteReadRepository = listing

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
        """Obsidian's best matches that are noesis notes of `scope`.

        Files without a `noesis:` block are not notes and are dropped, as are other scopes.

        Raises:
            ObsidianMcpError: Obsidian is unreachable or answered something unusable.
        """
        if not text.strip():
            return self._result([])
        async with self._client.session() as session:
            answer: JsonValue = await session.call("search_simple", {"query": text})
            ranked: list[tuple[float, str]] = []
            for hit in _hits(answer):
                path: str | None = _hit_path(hit)
                if path is not None:
                    ranked.append((_hit_score(hit), path))
            ranked.sort(key=lambda item: item[0])  # lowest score is best; stable on ties
            notes: list[NoteSummaryDto] = []
            for _, path in ranked:
                if len(notes) >= limit:
                    break
                summary: NoteSummaryDto | None = self._mapper.to_summary(
                    path, await self._text(session, path)
                )
                if summary is not None and (scope is None or summary.scope == scope.value):
                    notes.append(summary)
            return self._result(notes)

    @staticmethod
    def _result(notes: list[NoteSummaryDto]) -> NoteSearchResultDto:
        return NoteSearchResultDto(notes=tuple(notes), backend=SearchEngineEnum.OBSIDIAN_MCP)

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Delegated to the filesystem repository."""
        return await self._listing.list_notes(scope=scope, origin=origin)

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        """Delegated to the filesystem repository."""
        return await self._listing.find_active(scope, kind)

    async def find_by_id(
        self, note_id: NoteId, *, scope: NoteScope | None
    ) -> NoteSummaryDto | None:
        """Delegated to the filesystem repository."""
        return await self._listing.find_by_id(note_id, scope=scope)

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        """The note through `vault_read`, refused when it is not a note of `scope`.

        Raises:
            NoteStorageError: The path is outside the vault or the file is not an allowed note.
            ObsidianMcpError: Obsidian is unreachable or answered something unusable.
        """
        clean: str = checked_note_path(path)
        async with self._client.session() as session:
            text: str = await self._text(session, clean)
        note: NoteContentDto | None = self._mapper.to_content(clean, text)
        if note is None or (scope is not None and note.scope != scope.value):
            raise NoteStorageError(
                f"Refusing to read {path!r}: not a note of the allowed scope.",
                {"path": path, "scope": scope.value if scope else None},
            )
        return note

    @staticmethod
    async def _text(session: ObsidianMcpSession, path: str) -> str:
        answer: JsonValue = await session.call("vault_read", {"path": path})
        content: JsonValue = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(content, str):
            raise ObsidianMcpError(f"Obsidian MCP `vault_read` gave no content for {path}.")
        return content
