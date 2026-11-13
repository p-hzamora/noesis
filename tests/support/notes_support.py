"""In-memory fakes of the Notes ports, and builders for briefs and decisions."""

import hashlib
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
from noesis.bounded_context.notes.application.ports.ids import INoteIdGenerator
from noesis.bounded_context.notes.application.ports.manifest import IManifestProvider
from noesis.bounded_context.notes.application.ports.queue import IParkedCurationQueue
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.recall import IRecallAgent
from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.application.services.manifest import KindCatalog, Manifest
from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.repositories import INoteRepository
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteDraft,
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NotePath,
    NoteScope,
    NoteSection,
    NoteSlug,
    WorkBrief,
)
from noesis.bounded_context.notes.infrastructure.outbound.manifest import (
    YamlManifestProviderAdapter,
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
ID_ALPHABET: str = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class DefaultManifestProvider(IManifestProvider):
    """The packaged default manifest, with no user file."""

    async def load(self) -> Manifest:
        return await YamlManifestProviderAdapter(None).load()


CROCKFORD: str = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def path_note_id(path: str) -> NoteId:
    """A valid, stable `NoteId` derived from a note path, so fixtures need no generator."""
    number: int = int.from_bytes(hashlib.sha256(path.encode("utf-8")).digest()[:16], "big")
    chars: list[str] = []
    for _ in range(26):
        chars.append(CROCKFORD[number & 31])
        number >>= 5
    return NoteId(value="".join(reversed(chars)))


def default_catalog() -> KindCatalog:
    """The kind catalog of the packaged default manifest."""
    return YamlManifestProviderAdapter(None).load_now().catalog()


class SequentialIds(INoteIdGenerator):
    """Ids `01ARZ3NDEKTSV4RRFFQ69G5FA<A, B, C...>`, one per call."""

    def __init__(self) -> None:
        self.issued: int = 0

    def new_id(self) -> NoteId:
        letter: str = ID_ALPHABET[10 + self.issued]
        self.issued += 1
        return NoteId(value=f"01ARZ3NDEKTSV4RRFFQ69G5FA{letter}")


def a_scope(repository: str = "demo") -> NoteScope:
    """The scope of a repository."""
    return NoteScope.for_repository(repository)


def a_content(
    path: str = "repos/demo/decisions/use-ttl-cache.md",
    *,
    title: str = "Use a TTL cache",
    kind: str = "decision",
    origin: str = "manual",
    updated: str | None = "2026-11-01",
    content: str = "x",
) -> NoteContentDto:
    """A note's full content with sensible defaults."""
    return NoteContentDto(
        id=path_note_id(path).value,
        scope="repo:demo",
        path=path,
        title=title,
        kind=kind,
        origin=origin,
        updated=updated,
        content=content,
    )


def a_summary(
    path: str = "repos/demo/decisions/use-ttl-cache.md",
    *,
    id: str | None = None,
    scope: str = "repo:demo",
    title: str = "Use a TTL cache",
    kind: str = "decision",
    origin: str = "auto",
    updated: str | None = "2026-10-30",
    snippet: str = "Keep tokens in memory.",
) -> NoteSummaryDto:
    """A note summary with sensible defaults."""
    return NoteSummaryDto(
        id=id or path_note_id(path).value,
        scope=scope,
        path=path,
        title=title,
        kind=kind,
        origin=origin,
        updated=updated,
        snippet=snippet,
    )


class FixedClock(IClock):
    """A clock frozen at `NOW` unless told otherwise."""

    def __init__(self, now: datetime = NOW) -> None:
        self.current: datetime = now

    def now(self) -> datetime:
        return self.current


class InMemoryNoteRepository(INoteRepository):
    """Notes in a dict by path; `save` stages, the unit of work publishes on commit.

    `get_errors` scripts storage failures: each `get` pops and raises one while any remain.
    """

    def __init__(self) -> None:
        self.stored: dict[str, Note] = {}
        self.staged: dict[str, Note] = {}
        self.get_errors: list[NoteStorageError] = []

    async def get(self, path: NotePath) -> Note | None:
        if self.get_errors:
            raise self.get_errors.pop(0)
        return self.staged.get(path.value) or self.stored.get(path.value)

    async def exists(self, path: NotePath) -> bool:
        return path.value in self.staged or path.value in self.stored

    async def save(self, note: Note) -> None:
        self.staged[note.path.value] = note


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

    async def search(
        self, text: str, *, scope: NoteScope | None, limit: int
    ) -> NoteSearchResultDto:
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

    async def find_active(self, scope: NoteScope, kind: NoteKind) -> list[NoteSummaryDto]:
        return [n for n in self.notes if n.scope == scope.value and n.kind == kind.value]

    async def find_by_id(
        self, note_id: NoteId, *, scope: NoteScope | None
    ) -> NoteSummaryDto | None:
        return next(
            (
                n
                for n in self.notes
                if n.id == note_id.value and (scope is None or n.scope == scope.value)
            ),
            None,
        )

    async def read_note(self, path: str, *, scope: NoteScope | None) -> NoteContentDto:
        self.read_paths.append(path)
        if path in self.unreadable:
            raise NoteStorageError(f"Cannot read the note {path}.", {"path": path})
        note: NoteSummaryDto = next(note for note in self.notes if note.path == path)
        return NoteContentDto(
            id=note.id,
            scope=note.scope,
            path=note.path,
            title=note.title,
            kind=note.kind,
            origin=note.origin,
            updated=note.updated,
            content=self.bodies.get(path, note.snippet),
        )

    async def list_notes(
        self, *, scope: NoteScope | None, origin: NoteOriginEnum | None
    ) -> list[NoteSummaryDto]:
        return [
            note
            for note in self.notes
            if (origin is None or note.origin == origin.value)
            and (scope is None or note.scope == scope.value)
        ]


class ScriptedCurator(ICurator):
    """Answers from a script: each entry is a tuple of decisions or an error message to raise."""

    def __init__(self, *script: tuple[CurationDecision, ...] | str) -> None:
        self._script: list[tuple[CurationDecision, ...] | str] = list(script)
        self.calls: int = 0
        self.related_seen: list[Sequence[NoteSummaryDto]] = []
        self.briefs_seen: list[WorkBrief] = []

    async def judge(
        self, brief: WorkBrief, related: Sequence[NoteSummaryDto], catalog: KindCatalog
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
        scope: NoteScope,
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
                "scope": scope.value,
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
    kind: str = "decision",
    title: str = "Use a TTL cache",
) -> NoteDraft:
    """A draft with one section."""
    return NoteDraft(
        kind=NoteKind(value=kind),
        slug=NoteSlug(value=slug),
        title=title,
        sections=(NoteSection(heading="Decision", body="Keep tokens in memory."),),
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
        id=NoteId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV"),
        scope=a_scope(),
        origin=origin,
        path=NotePath(value=f"repos/demo/decisions/{slug}.md"),
        draft=a_draft(slug=slug),
        required_sections=("Decision", "Rationale"),
        now=NOW,
    )


def note_file(
    path: str,
    *,
    title: str,
    kind: str = "decision",
    origin: str = "manual",
    updated: str = "2026-10-02",
    body: str = "",
    scope: str | None = None,
) -> str:
    """The Markdown of a noesis note at `path` (id derived from it, scope from its folder)."""
    parts: list[str] = path.split("/")
    if scope is None:
        scope = f"{'repo' if parts[0] == 'repos' else 'topic'}:{parts[1]}"
    heading: str = {"gotcha": "Symptom", "run": "Outcome"}.get(kind, "Decision")
    return (
        f"---\nnoesis:\n  id: {path_note_id(path).value}\n  scope: {scope}\n  kind: {kind}\n"
        f"  origin: {origin}\n  sources: []\n  updated: {updated}\n---\n\n"
        f"# {title}\n\n## {heading}\n\n{body}\n"
    )
