"""Recall the notes worth reading before starting a task."""

from datetime import date

from pydantic import Field

from noesis.bounded_context.notes.application.dtos import (
    NoteSearchResultDto,
    NoteSummaryDto,
    RecallDigestDto,
    RecallEntryDto,
)
from noesis.bounded_context.notes.application.mappers import (
    CHARS_PER_TOKEN,
    OVERFETCH_CAP,
    OVERFETCH_FACTOR,
    recall_terms,
)
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.domain.policies import RecallRankingPolicy
from noesis.bounded_context.notes.domain.value_objects import (
    NoteArea,
    NoteKindEnum,
    NoteOriginEnum,
    RecallCandidate,
    RecallWeights,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

ELLIPSIS: str = "…"


class RecallNotesQuery(FrozenObject):
    """Find the notes that help with `task`.

    Attributes:
        task: One sentence on what is about to be done.
        area: Restrict to one area (e.g. `repos/noesis`); None searches everything.
        limit: Maximum number of entries.
        budget_tokens: Rough size cap of the digest (4 characters per token); 0 is unlimited.
    """

    task: str = Field(min_length=1)
    area: str | None = None
    limit: int = Field(default=5, ge=1, le=20)
    budget_tokens: int = Field(default=1000, ge=0)


class RecallNotesHandler(IHandler[RecallNotesQuery, RecallDigestDto]):
    """Search with the task's keywords, re-rank the hits and trim them to the budget."""

    def __init__(self, *, read_repository: INoteReadRepository, clock: IClock) -> None:
        self._read_repository: INoteReadRepository = read_repository
        self._clock: IClock = clock
        self._policy: RecallRankingPolicy = RecallRankingPolicy(RecallWeights())

    async def handle(self, action: RecallNotesQuery) -> RecallDigestDto:
        """A digest of the best notes for the task: pointers and snippets, never bodies.

        Raises:
            NoRecallTermsError: The task has no keywords left to search for.
        """
        terms: str = recall_terms(action.task)
        area: NoteArea | None = NoteArea(value=action.area) if action.area else None
        found: NoteSearchResultDto = await self._read_repository.search(
            terms, area=area, limit=min(action.limit * OVERFETCH_FACTOR, OVERFETCH_CAP)
        )
        by_path: dict[str, NoteSummaryDto] = {}
        for note in found.notes:
            by_path.setdefault(note.path, note)
        candidates: list[RecallCandidate] = [
            self._candidate(note, rank) for rank, note in enumerate(by_path.values())
        ]
        ranked: tuple[str, ...] = self._policy.rank(candidates, today=self._clock.now().date())
        entries: list[RecallEntryDto] = [
            self._entry(by_path[path]) for path in ranked[: action.limit]
        ]
        fitted: tuple[RecallEntryDto, ...] = self._fit(entries, action.budget_tokens)
        return RecallDigestDto(
            entries=fitted,
            considered=len(by_path),
            omitted=len(by_path) - len(fitted),
            backend=found.backend,
        )

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
