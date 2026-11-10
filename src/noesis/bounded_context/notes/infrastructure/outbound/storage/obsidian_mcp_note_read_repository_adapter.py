"""`INoteReadRepository` that searches through Obsidian's MCP server.

Obsidian indexes the whole vault (manual notes, `learning/<topic>/`, other know-how folders),
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
    NoteArea,
    NoteLocation,
    NoteOriginEnum,
)
from noesis.exceptions import DomainException, ObsidianMcpError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient, ObsidianMcpSession

from .mappers import NoteMapper, ParsedMarkdown
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

    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> NoteSearchResultDto:
        """Obsidian's best matches, restricted to `area`'s folder when given.

        Hits outside the noesis layout are kept (kind None, origin manual), because Obsidian
        also knows the notes noesis did not write.

        Raises:
            ObsidianMcpError: Obsidian is unreachable or answered something unusable.
        """
        if not text.strip():
            return self._result([])
        async with self._client.session() as session:
            answer: JsonValue = await session.call("search_simple", {"query": text})
            ranked: list[tuple[float, str]] = []
            # Check whether we can use Binary Tree to store the whole information to be able to sorte it faster
            for hit in _hits(answer):
                path: str | None = _hit_path(hit)
                if path is None or (area is not None and not path.startswith(f"{area.value}/")):
                    continue
                ranked.append((_hit_score(hit), path))
            ranked.sort(key=lambda item: item[0])  # lowest score is best; stable on ties
            return self._result([await self._summary(session, path) for _, path in ranked[:limit]])

    @staticmethod
    def _result(notes: list[NoteSummaryDto]) -> NoteSearchResultDto:
        return NoteSearchResultDto(notes=tuple(notes), backend=SearchEngineEnum.OBSIDIAN_MCP)

    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        """Delegated to the filesystem repository."""
        return await self._listing.list_notes(area=area, origin=origin)

    async def read_note(self, path: str, *, area: NoteArea | None) -> NoteContentDto:
        """The note through `vault_read`, refused when it is outside `area`.

        Raises:
            NoteStorageError: The path is outside the allowed scope.
            ObsidianMcpError: Obsidian is unreachable or answered something unusable.
        """
        clean: str = checked_note_path(path, area)
        async with self._client.session() as session:
            return await self._content(session, clean)

    async def _content(self, session: ObsidianMcpSession, path: str) -> NoteContentDto:
        answer: JsonValue = await session.call("vault_read", {"path": path})
        content: JsonValue = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(content, str):
            raise ObsidianMcpError(f"Obsidian MCP `vault_read` gave no content for {path}.")
        parsed: ParsedMarkdown = self._mapper.parse(content)
        updated: object = parsed.frontmatter.get("updated") or parsed.frontmatter.get("date")
        try:
            location = NoteLocation.parse(path)
        except DomainException:
            location = None
        stem: str = path.rsplit("/", 1)[-1].removesuffix(NOTE_SUFFIX)
        return NoteContentDto(
            path=path,
            title=parsed.title or (location.slug.value if location else stem),
            kind=location.kind.value if location else None,
            origin=location.origin.value if location else NoteOriginEnum.MANUAL.value,
            updated=str(updated) if updated else None,
            content=content,
        )

    async def _summary(self, session: ObsidianMcpSession, path: str) -> NoteSummaryDto:
        note: NoteContentDto = await self._content(session, path)
        parsed: ParsedMarkdown = self._mapper.parse(note.content)
        return NoteSummaryDto(
            path=note.path,
            title=note.title,
            kind=note.kind,
            origin=note.origin,
            updated=note.updated,
            snippet=self._mapper.snippet(parsed),
        )
