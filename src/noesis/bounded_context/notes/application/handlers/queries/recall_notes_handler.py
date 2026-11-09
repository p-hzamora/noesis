"""Recall what the notes say about a task: search, read the best notes, brief the agent."""

from datetime import date

from pydantic import Field

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
    RecallBriefingDto,
    RecallDigestDto,
    RecallEntryDto,
)
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.recall import IRecallAgent
from noesis.bounded_context.notes.application.services.recall import (
    CHARS_PER_TOKEN,
    OVERFETCH_FACTOR,
    PER_QUERY_CAP,
    BriefingGrounder,
    RecallQueryBuilder,
    SecretRedactor,
)
from noesis.bounded_context.notes.domain.policies import RecallRankingPolicy
from noesis.bounded_context.notes.domain.value_objects import (
    NoteArea,
    NoteKindEnum,
    NoteOriginEnum,
    RecallCandidate,
    RecallWeights,
)
from noesis.exceptions import (
    NoteStorageError,
    ObsidianMcpError,
    RecallAgentFailedError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.utils import FrozenObject

ELLIPSIS: str = "…"
RANK_FUSION_OFFSET: int = 60
DEFAULT_MAX_INPUT_CHARS: int = 60_000
CUT_MARKER: str = "\n\n[... note cut here to fit the size limit ...]"


class RecallNotesQuery(FrozenObject):
    """Find the notes that help with `task`.

    Attributes:
        task: One sentence on what is about to be done.
        area: Restrict to one area (e.g. `repos/noesis`); None searches everything.
        limit: Maximum number of notes (read for the briefing, or listed in the digest).
        budget_tokens: Rough size of the output (4 characters per token); 0 is unlimited. A
            digest is trimmed to it; a briefing is asked to aim for it.
        synthesize: Have an agent read the notes and write a briefing; False returns only the
            ranked digest, with no model involved.
    """

    task: str = Field(min_length=1)
    area: str | None = None
    limit: int = Field(default=5, ge=1, le=20)
    budget_tokens: int = Field(default=1000, ge=0)
    synthesize: bool = True


class RecallNotesHandler(IHandler[RecallNotesQuery, RecallDigestDto]):
    """Find the notes for a task, read the best ones and have an agent brief the task from them.

    Searches once per keyword and merges the hits (a search wants every word of a query), ranks
    them, reads the top `limit` notes in full with secrets masked and their text bounded, and
    asks the agent for a briefing that is then checked against the notes it was given.
    """

    def __init__(
        self,
        *,
        read_repository: INoteReadRepository,
        clock: IClock,
        agent: IRecallAgent | None = None,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    ) -> None:
        self._read_repository: INoteReadRepository = read_repository
        self._clock: IClock = clock
        self._agent: IRecallAgent | None = agent
        self._max_input_chars: int = max_input_chars
        self._policy: RecallRankingPolicy = RecallRankingPolicy(RecallWeights())

    async def handle(self, action: RecallNotesQuery) -> RecallDigestDto:
        """The briefing for the task, or only the digest when `synthesize` is off.

        With no note found, no agent runs and the result says `no_evidence`.

        Raises:
            NoRecallTermsError: The task has no keywords left to search for.
            NoteStorageError: Notes were found but none could be read.
            RecallAgentFailedError: The agent is missing, failed or answered something unusable
                (`candidates` in its metadata lists the notes that would have been read).
        """
        queries: tuple[str, ...] = RecallQueryBuilder.queries(action.task)
        area: NoteArea | None = NoteArea(value=action.area) if action.area else None
        by_path, backend = await self._search(queries, area, action.limit)
        candidates: list[RecallCandidate] = [
            self._candidate(note, rank) for rank, note in enumerate(by_path.values())
        ]
        ranked: tuple[str, ...] = self._policy.rank(candidates, today=self._clock.now().date())
        if not action.synthesize:
            entries: list[RecallEntryDto] = [
                self._entry(by_path[path]) for path in ranked[: action.limit]
            ]
            fitted: tuple[RecallEntryDto, ...] = self._fit(entries, action.budget_tokens)
            return RecallDigestDto(
                entries=fitted,
                considered=len(by_path),
                omitted=len(by_path) - len(fitted),
                backend=backend,
                synthesis="digest",
            )
        if not ranked:
            return RecallDigestDto(
                entries=(), considered=0, omitted=0, backend=backend, synthesis="no_evidence"
            )
        return await self._brief(action, area, by_path, ranked[: action.limit], backend)

    async def _search(
        self, queries: tuple[str, ...], area: NoteArea | None, limit: int
    ) -> tuple[dict[str, NoteSummaryDto], SearchEngineEnum]:
        """Hits of every query merged by reciprocal rank: a note several keywords find rises.

        Each query counts for less the more notes it matches, so a rare keyword outweighs a
        generic one such as `working`.
        """
        score: dict[str, float] = {}
        seen: dict[str, NoteSummaryDto] = {}
        answers: list[NoteSearchResultDto] = []
        for query in queries:
            found: NoteSearchResultDto = await self._read_repository.search(
                query, area=area, limit=min(limit * OVERFETCH_FACTOR, PER_QUERY_CAP)
            )
            answers.append(found)
            weight: float = 1 / max(len(found.notes), 1)  # a keyword few notes have says more
            for rank, path in enumerate(dict.fromkeys(note.path for note in found.notes)):
                score[path] = score.get(path, 0.0) + weight / (RANK_FUSION_OFFSET + rank)
            for note in found.notes:
                seen.setdefault(note.path, note)
        order: list[str] = sorted(score, key=lambda path: -score[path])  # stable: first seen wins
        # the last answer names who answered after any fallback; queries are never empty
        return {path: seen[path] for path in order}, answers[-1].backend

    async def _brief(
        self,
        action: RecallNotesQuery,
        area: NoteArea | None,
        by_path: dict[str, NoteSummaryDto],
        paths: tuple[str, ...],
        backend: SearchEngineEnum,
    ) -> RecallDigestDto:
        if self._agent is None:
            raise RecallAgentFailedError(
                "No recall agent is configured.", next_steps=["Use --no-synthesis."]
            )
        warnings: list[str] = []
        notes: list[NoteContentDto] = await self._read(paths, area, warnings)
        if not notes:
            raise NoteStorageError(
                f"Found {len(paths)} notes but could not read any of them.",
                {"candidates": list(paths)},
                next_steps=["Check that the vault is reachable, or use --no-synthesis."],
            )
        try:
            draft: RecallBriefingDto = await self._agent.brief(
                action.task, notes, target_tokens=action.budget_tokens
            )
        except RecallAgentFailedError as error:
            error.metadata["candidates"] = [note.path for note in notes]
            error.next_steps = (*error.next_steps, "Use --no-synthesis for the ranked notes only.")
            raise
        briefing: RecallBriefingDto = BriefingGrounder.ground(draft, notes)
        briefing = briefing.model_copy(
            update={"markdown": BriefingGrounder.markdown(action.task, briefing, notes)}
        )
        if briefing.unsupported:
            warnings.append(
                f"{len(briefing.unsupported)} statements cited no note that was read and were set aside."
            )
        entries: tuple[RecallEntryDto, ...] = tuple(self._entry(by_path[n.path]) for n in notes)
        return RecallDigestDto(
            entries=entries,
            considered=len(by_path),
            omitted=len(by_path) - len(entries),
            backend=backend,
            synthesis="briefing",
            briefing=briefing,
            warnings=tuple(warnings),
        )

    async def _read(
        self, paths: tuple[str, ...], area: NoteArea | None, warnings: list[str]
    ) -> list[NoteContentDto]:
        """The notes in full, secrets masked and each cut to its share of the input limit."""
        share: int = max(self._max_input_chars // len(paths), 1)
        notes: list[NoteContentDto] = []
        masked: int = 0
        for path in paths:
            try:
                note: NoteContentDto = await self._read_repository.read_note(path, area=area)
            except (NoteStorageError, ObsidianMcpError) as error:
                warnings.append(f"Could not read {path}: {error.args[0]}")
                continue
            content, hidden = SecretRedactor.redact(note.content)
            masked += hidden
            if len(content) > share:
                content = content[:share].rstrip() + CUT_MARKER
                warnings.append(f"Cut {path} to {share} characters to fit the size limit.")
            notes.append(note.model_copy(update={"content": content}))
        if masked:
            warnings.append(
                f"Masked {masked} possible secrets before sending the notes to the agent."
            )
        return notes

    @staticmethod
    def _candidate(note: NoteSummaryDto, rank: int) -> RecallCandidate:
        """The note as ranking sees it; values noesis does not know become neutral."""
        try:
            kind: NoteKindEnum | None = NoteKindEnum(note.kind) if note.kind else None
        except ValueError:
            kind = None
        try:
            origin: NoteOriginEnum = NoteOriginEnum(note.origin)
        except ValueError:
            origin = NoteOriginEnum.AUTO
        try:
            updated: date | None = date.fromisoformat(note.updated[:10]) if note.updated else None
        except ValueError:
            updated = None
        return RecallCandidate(path=note.path, kind=kind, origin=origin, updated=updated, rank=rank)

    @staticmethod
    def _entry(note: NoteSummaryDto) -> RecallEntryDto:
        return RecallEntryDto(
            kind=note.kind,
            title=note.title,
            path=note.path,
            date=note.updated,
            snippet=note.snippet,
        )

    @staticmethod
    def _size(entry: RecallEntryDto) -> int:
        return (
            len(entry.kind or "")
            + len(entry.title)
            + len(entry.path)
            + len(entry.date or "")
            + len(entry.snippet)
        )

    def _fit(self, entries: list[RecallEntryDto], budget_tokens: int) -> tuple[RecallEntryDto, ...]:
        """Entries within the budget: drop the lowest ranked, then shorten snippets.

        First entries are dropped from the end while even their bare form (no snippet) does
        not fit. The characters left go to the snippets in rank order, so the best entry keeps
        the most text. A budget of 0 is unlimited.
        """
        if budget_tokens == 0:
            return tuple(entries)
        budget: int = budget_tokens * CHARS_PER_TOKEN
        bare: list[RecallEntryDto] = [entry.model_copy(update={"snippet": ""}) for entry in entries]
        while bare and sum(self._size(entry) for entry in bare) > budget:
            bare.pop()
            entries = entries[:-1]
        remaining: int = budget - sum(self._size(entry) for entry in bare)
        fitted: list[RecallEntryDto] = []
        for entry in entries:
            snippet: str = self._shorten(entry.snippet, remaining)
            remaining -= len(snippet)
            fitted.append(entry.model_copy(update={"snippet": snippet}))
        return tuple(fitted)

    @staticmethod
    def _shorten(snippet: str, room: int) -> str:
        if len(snippet) <= room:
            return snippet
        if room <= 0:
            return ""
        return snippet[: room - 1].rstrip() + ELLIPSIS
