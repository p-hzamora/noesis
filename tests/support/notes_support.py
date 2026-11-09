"""In-memory fakes of the Notes ports, and builders for briefs and decisions."""

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from noesis.bounded_context.notes.application.dtos import (
    ApplyFailureRecordDto,
    NoteContentDto,
    NoteSearchResultDto,
    NoteSummaryDto,
    ParkedCurationDto,
    RecallBriefingDto,
)
from noesis.bounded_context.notes.application.ports.curation import ICurator
from noesis.bounded_context.notes.application.ports.failures import IApplyFailureLog
from noesis.bounded_context.notes.application.ports.queue import IParkedCurationQueue
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.recall import IRecallAgent
from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.repositories import INoteRepository
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteArea,
    NoteDraft,
    NoteKindEnum,
    NoteLocation,
    NoteOriginEnum,
    NoteSection,
    NoteSlug,
    WorkBrief,
)
from noesis.exceptions import (
    CuratorFailedError,
    NoteStorageError,
    RecallAgentFailedError,
)
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import CommitRefContract, WorkBriefContract
from noesis.shared_kernel.enums import SearchEngineEnum

NOW: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


class FixedClock(IClock):
    """A clock frozen at `NOW` unless told otherwise."""

    def __init__(self, now: datetime = NOW) -> None:
        self.current: datetime = now

    def now(self) -> datetime:
        return self.current


class InMemoryNoteRepository(INoteRepository):
    """Notes in a dict; `save` stages, the unit of work publishes on commit.

    `get_errors` scripts storage failures: each `get` pops and raises one while any remain.
    """

    def __init__(self) -> None:
        self.stored: dict[str, Note] = {}
        self.staged: dict[str, Note] = {}
        self.get_errors: list[NoteStorageError] = []

    async def get(self, location: NoteLocation) -> Note | None:
        if self.get_errors:
            raise self.get_errors.pop(0)
        path: str = location.relative_path
        return self.staged.get(path) or self.stored.get(path)

    async def save(self, note: Note) -> None:
        self.staged[note.location.relative_path] = note


class InMemoryNotesUnitOfWork(INotesUnitOfWork):
    """Commits staged notes into `stored`; counts commits.

    `commit_errors` scripts storage failures: each `commit` pops and raises one while any remain
    (the stage is then dropped on exit, like a real writer that did not confirm).
    """

    def __init__(
        self,
        repository: InMemoryNoteRepository,
        commit_errors: list[NoteStorageError] | None = None,
    ) -> None:
        self._repository: InMemoryNoteRepository = repository
        self.commit_errors: list[NoteStorageError] = (
            commit_errors if commit_errors is not None else []
        )
        self.commits: int = 0

    @property
    def notes(self) -> INoteRepository:
        return self._repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()

    async def commit(self) -> None:
        if self.commit_errors:
            raise self.commit_errors.pop(0)
        self._repository.stored.update(self._repository.staged)
        self._repository.staged.clear()
        self.commits += 1

    async def rollback(self) -> None:
        self._repository.staged.clear()


class InMemoryNoteReadRepository(INoteReadRepository):
    """Returns preset summaries and records the queries and limits it received.

    A search returns every note whose title or snippet contains one of the query's words, or
    every note when `match_all` (the default, as before). `bodies` gives `read_note` its text
    (default: the snippet); `unreadable` lists paths whose read fails.
    """

    def __init__(
        self,
        notes: Sequence[NoteSummaryDto] = (),
        *,
        bodies: dict[str, str] | None = None,
        unreadable: Sequence[str] = (),
        match_all: bool = True,
    ) -> None:
        self.notes: list[NoteSummaryDto] = list(notes)
        self.queries: list[str] = []
        self.limits: list[int] = []
        self.read_paths: list[str] = []
        self.bodies: dict[str, str] = bodies or {}
        self.unreadable: tuple[str, ...] = tuple(unreadable)
        self.match_all: bool = match_all

    async def search(self, text: str, *, area: NoteArea | None, limit: int) -> NoteSearchResultDto:
        self.queries.append(text)
        self.limits.append(limit)
        words: list[str] = text.lower().split()
        hits: list[NoteSummaryDto] = [
            note
            for note in self.notes
            if self.match_all
            or any(word in f"{note.title} {note.snippet} {note.path}".lower() for word in words)
        ]
        return NoteSearchResultDto(notes=tuple(hits[:limit]), backend=SearchEngineEnum.FILESYSTEM)

    async def read_note(self, path: str, *, area: NoteArea | None) -> NoteContentDto:
        self.read_paths.append(path)
        if path in self.unreadable:
            raise NoteStorageError(f"Cannot read the note {path}.", {"path": path})
        note: NoteSummaryDto = next(note for note in self.notes if note.path == path)
        return NoteContentDto(
            path=note.path,
            title=note.title,
            kind=note.kind,
            origin=note.origin,
            updated=note.updated,
            content=self.bodies.get(path, note.snippet),
        )

    async def list_notes(
        self, *, area: NoteArea | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        return [note for note in self.notes if origin is None or note.origin == origin.value]


class ScriptedCurator(ICurator):
    """Answers from a script: each entry is a tuple of decisions or an error message to raise."""

    def __init__(self, *script: tuple[CurationDecision, ...] | str) -> None:
        self._script: list[tuple[CurationDecision, ...] | str] = list(script)
        self.calls: int = 0
        self.related_seen: list[Sequence[NoteSummaryDto]] = []
        self.briefs_seen: list[WorkBrief] = []

    async def judge(
        self, brief: WorkBrief, related: Sequence[NoteSummaryDto]
    ) -> tuple[CurationDecision, ...]:
        self.calls += 1
        self.briefs_seen.append(brief)
        self.related_seen.append(related)
        step: tuple[CurationDecision, ...] | str = self._script.pop(0)
        if isinstance(step, str):
            raise CuratorFailedError(step)
        return step


class ScriptedRecallAgent(IRecallAgent):
    """Answers with a preset briefing, or raises when given an error message."""

    def __init__(self, answer: RecallBriefingDto | str) -> None:
        self._answer: RecallBriefingDto | str = answer
        self.calls: list[tuple[str, tuple[NoteContentDto, ...], int]] = []

    async def brief(
        self, task: str, notes: Sequence[NoteContentDto], *, target_tokens: int
    ) -> RecallBriefingDto:
        self.calls.append((task, tuple(notes), target_tokens))
        if isinstance(self._answer, str):
            raise RecallAgentFailedError(self._answer)
        return self._answer


class InMemoryParkedQueue(IParkedCurationQueue):
    """Parked briefs in a dict; tickets are sequential."""

    def __init__(self) -> None:
        self.parked: dict[str, tuple[WorkBriefContract, str]] = {}

    async def park(self, brief: WorkBriefContract, *, error: str, now: datetime) -> str:
        ticket: str = f"ticket-{len(self.parked) + 1}"
        self.parked[ticket] = (brief, error)
        return ticket

    async def list_parked(self) -> list[ParkedCurationDto]:
        return [
            ParkedCurationDto(
                ticket=ticket,
                repository=brief.repository,
                head=brief.head,
                parked_at=NOW.isoformat(),
                error=error,
            )
            for ticket, (brief, error) in self.parked.items()
        ]

    async def get(self, ticket: str) -> WorkBriefContract | None:
        entry: tuple[WorkBriefContract, str] | None = self.parked.get(ticket)
        return entry[0] if entry else None

    async def discard(self, ticket: str) -> None:
        self.parked.pop(ticket, None)


class InMemoryApplyFailureLog(IApplyFailureLog):
    """Failed-apply records in a list; `fail_with` scripts a record that cannot be written."""

    def __init__(self, fail_with: NoteStorageError | None = None) -> None:
        self.records: list[dict[str, object]] = []
        self.fail_with: NoteStorageError | None = fail_with

    async def record(
        self,
        *,
        raw_payload: str,
        area: NoteArea,
        commits: tuple[str, ...],
        session: str | None,
        errors: Sequence[str],
        now: datetime,
    ) -> ApplyFailureRecordDto:
        if self.fail_with is not None:
            raise self.fail_with
        self.records.append(
            {
                "raw_payload": raw_payload,
                "area": area.value,
                "commits": commits,
                "session": session,
                "errors": list(errors),
            }
        )
        ticket: str = f"apply-{len(self.records)}"
        folder: str = "/state/notes/apply-failed"
        return ApplyFailureRecordDto(
            ticket=ticket,
            path=f"{folder}/{ticket}.json",
            payload_path=f"{folder}/{ticket}.payload.json",
        )


def a_brief(repository: str = "demo", session_id: str = "abcd1234ef") -> WorkBriefContract:
    """A small, valid work brief."""
    return WorkBriefContract(
        session_id=session_id,
        repository=repository,
        repository_path=f"/work/{repository}",
        branch="main",
        head="8e6d3b5fe598c6bf",
        commits=(CommitRefContract(sha="8e6d3b5fe598c6bf", subject="feat: add TTL cache"),),
        diff_stat=("app.py | 36 +++",),
        goal="make login faster",
        session_excerpt="A: chose a TTL cache over Redis: single instance.",
    )


def a_draft(
    slug: str = "use-ttl-cache",
    kind: NoteKindEnum = NoteKindEnum.DECISION,
    title: str = "Use a TTL cache",
) -> NoteDraft:
    """A draft with one section of its kind."""
    return NoteDraft(
        kind=kind,
        slug=NoteSlug(value=slug),
        title=title,
        sections=(NoteSection(heading=kind.required_sections[0], body="Keep tokens in memory."),),
    )


def a_decision(
    action: CurationActionEnum = CurationActionEnum.CREATE,
    draft: NoteDraft | None = None,
    candidate: str = "ttl",
) -> CurationDecision:
    """A curator decision; SKIP decisions carry no draft."""
    return CurationDecision(
        action=action,
        candidate=candidate,
        reason="single instance, no shared state",
        draft=None if action is CurationActionEnum.SKIP else (draft or a_draft()),
    )


def a_note(origin: NoteOriginEnum = NoteOriginEnum.AUTO, slug: str = "use-ttl-cache") -> Note:
    """A stored note in `repos/demo`."""
    return Note.create(
        area=NoteArea.for_repository("demo"), origin=origin, draft=a_draft(slug=slug), now=NOW
    )
