"""Fakes and builders for the curation tests: an in-memory inbox, a curator, a finder, a spy per
command handler and a ready-wired environment over the in-memory Knowledge store.

The C2 and C4 command handlers are the real ones over `FakeKnowledgeStore`, wrapped in spies
that record each call's idempotency key and can fail on a chosen key. The fake store keeps the
ledger, so a replayed step returns the original ids exactly as the real store does.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tests.support.knowledge_support import DEFAULT_SPACE_KEY, MutableClock
from tests.support.review_fakes import ReviewEnv, make_review_env

from noesis.bounded_context.knowledge.application.dtos import (
    CaptureResultDto,
    ProposeAssertionResultDto,
    RelatedLookupDto,
    RelatedRecordDto,
    ReviseResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_curation_handler import (
    ApplyCurationCommand,
    ApplyCurationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.ingest_work_brief_handler import (
    IngestWorkBriefCommand,
    IngestWorkBriefHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.register_curation_plan_handler import (
    RegisterCurationPlanHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retry_parked_curation_handler import (
    RetryParkedCurationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_parked_curations_handler import (
    ListParkedCurationsHandler,
)
from noesis.bounded_context.knowledge.application.ports.curation import (
    CurationTicket,
    ICurationInbox,
    ICurator,
    StepOutcome,
)
from noesis.bounded_context.knowledge.application.services.curation_process_manager import (
    CurationProcessManager,
    StepHook,
)
from noesis.bounded_context.knowledge.application.services.curation_runner import (
    CurationRunner,
)
from noesis.bounded_context.knowledge.domain.services import (
    CaptureKeyPolicy,
    CurationAdmissionPolicy,
    CurationProgressPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    CandidateKindEnum,
    CurationCandidate,
    CurationPlan,
    CurationProgress,
    CurationSubmission,
    CurationSubtypes,
    WorkBrief,
)
from noesis.exceptions import CurationInboxFailedError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract, RecordSearchHitItem
from noesis.shared_kernel.contracts.work_brief_contract import CommitRefContract

SHA1: str = "1" * 40
SHA2: str = "2" * 40
SESSION: str = "sess-c7-0001"
PROJECT: str = "c7-fixture"
SECRET_GH: str = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SECRET_AWS: str = "AKIA" + "ABCDEFGHIJKLMNOP"
SECRET_PW: str = "password=hunter2hunter2"
USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
AGENT: Actor = Actor(kind=ActorKindEnum.AGENT, name="claude-code", session="s-apply")


def brief_contract(
    *,
    goal: str = "Harden the parser",
    excerpt: str = "We fixed the offset bug.",
    session: str = SESSION,
    shas: tuple[str, ...] = (SHA1, SHA2),
) -> WorkBriefContract:
    """The shared `BRIEF_2C` fixture of the spec: two commits, oldest first."""
    subjects: tuple[str, ...] = ("add parser", "fix parser offset", "tidy")
    return WorkBriefContract(
        session_id=session,
        repository=PROJECT,
        repository_path="/work/c7-fixture",
        branch="main",
        head=shas[-1],
        commits=tuple(
            CommitRefContract(sha=sha, subject=subjects[index]) for index, sha in enumerate(shas)
        ),
        goal=goal,
        session_excerpt=excerpt,
    )


def experience(
    key: str = "e1", subtype: str = "observation", body: str = "Offsets were off by one on CRLF."
) -> CurationCandidate:
    """An experience candidate."""
    return CurationCandidate(kind=CandidateKindEnum.EXPERIENCE, key=key, subtype=subtype, body=body)


def knowledge(
    key: str = "k1",
    *,
    subtype: str = "convention",
    title: str | None = "Parser errors carry the byte offset",
    body: str = "Every parser error reports the byte offset.",
    target: str | None = None,
    evidence: tuple[str, ...] = (),
    reason: str | None = None,
) -> CurationCandidate:
    """A knowledge candidate."""
    return CurationCandidate(
        kind=CandidateKindEnum.KNOWLEDGE,
        key=key,
        subtype=subtype,
        title=title,
        body=body,
        target_record_id=target,
        evidence_keys=evidence,
        reason=reason,
    )


def skip(key: str = "s1", reason: str = "already in the README") -> CurationCandidate:
    """A skip candidate."""
    return CurationCandidate(kind=CandidateKindEnum.SKIP, key=key, reason=reason)


ANSWER_EK: tuple[CurationCandidate, ...] = (experience(), knowledge())
ANSWER_3K: tuple[CurationCandidate, ...] = (knowledge("k1"), knowledge("k2"), knowledge("k3"))


class InMemoryCurationInbox(ICurationInbox):
    """The inbox contract over a dict: write-once plan, compare-and-advance, per-ticket lock."""

    def __init__(self, clock: MutableClock) -> None:
        self._clock: MutableClock = clock
        self.tickets: dict[str, CurationTicket] = {}
        self.kept: list[str] = []
        self._locks: dict[str, asyncio.Lock] = {}

    async def stage(self, submission: CurationSubmission) -> CurationTicket:
        ticket: str = CaptureKeyPolicy.ticket_of(submission.submission_key)
        if ticket not in self.tickets:
            now: datetime = self._clock.now()
            self.tickets[ticket] = CurationTicket(
                ticket=ticket,
                submission=submission,
                progress=CurationProgressPolicy.initial(),
                created_at=now,
                updated_at=now,
            )
        return self.tickets[ticket]

    async def save_plan(
        self, ticket: str, plan: CurationPlan, *, related_lookup: RelatedLookupDto | None = None
    ) -> None:
        current: CurationTicket = self.tickets[ticket]
        if current.plan is not None and current.plan != plan:
            raise CurationInboxFailedError("A different plan was already saved.")
        if current.plan is None:
            self.tickets[ticket] = current.model_copy(
                update={"plan": plan, "related_lookup": related_lookup}
            )

    async def advance(
        self, ticket: str, expected: CurationProgress, to: CurationProgress
    ) -> CurationTicket:
        current: CurationTicket = self.tickets[ticket]
        if current.progress != expected:
            raise CurationInboxFailedError("The ticket changed since it was read.")
        now: datetime = self._clock.now()
        self.tickets[ticket] = current.model_copy(
            update={
                "progress": to,
                "updated_at": now,
                "parked_at": now if to.is_failed else None,
            }
        )
        return self.tickets[ticket]

    async def record_step(self, ticket: str, outcome: StepOutcome) -> None:
        current: CurationTicket = self.tickets[ticket]
        steps = (
            *(s for s in current.steps if (s.ordinal, s.step) != (outcome.ordinal, outcome.step)),
            outcome,
        )
        self.tickets[ticket] = current.model_copy(update={"steps": steps})

    async def get(self, ticket: str) -> CurationTicket | None:
        return self.tickets.get(ticket)

    async def list_parked(self) -> tuple[CurationTicket, ...]:
        parked = [t for t in self.tickets.values() if t.progress.is_failed]
        return tuple(sorted(parked, key=lambda t: t.parked_at or t.updated_at))

    @asynccontextmanager
    async def locked(self, ticket: str) -> AsyncIterator[None]:
        lock: asyncio.Lock = self._locks.setdefault(ticket, asyncio.Lock())
        async with lock:
            yield

    async def keep_rejected(self, payload_text: str) -> str:
        self.kept.append(payload_text)
        return f"/inbox/rejected/{len(self.kept)}.json"

    async def remove(self, ticket: str) -> None:
        self.tickets.pop(ticket, None)


class FakeCurator(ICurator):
    """Answers with canned candidates, or raises; records what it was asked."""

    def __init__(
        self,
        answer: Sequence[CurationCandidate] = ANSWER_EK,
        *,
        failures: Sequence[Exception] = (),
    ) -> None:
        self.answer: tuple[CurationCandidate, ...] = tuple(answer)
        self.failures: list[Exception] = list(failures)
        self.calls: list[tuple[WorkBrief, tuple[RelatedRecordDto, ...]]] = []

    async def judge(
        self, brief: WorkBrief, related: Sequence[RelatedRecordDto], subtypes: CurationSubtypes
    ) -> tuple[CurationCandidate, ...]:
        self.calls.append((brief, tuple(related)))
        if self.failures:
            raise self.failures.pop(0)
        return self.answer


class FakeRelatedFinder:
    """Answers with hits for the given record ids, or raises."""

    def __init__(
        self, record_ids: Sequence[str] = (), *, error: Exception | None = None, pending: int = 0
    ) -> None:
        self.record_ids: tuple[str, ...] = tuple(record_ids)
        self.error: Exception | None = error
        self.pending: int = pending
        self.calls: list[tuple[str, str | None, int]] = []

    async def find(
        self, text: str, *, space_id: str, project_key: str | None, limit: int
    ) -> RecordSearchHitContract:
        self.calls.append((text, project_key, limit))
        if self.error is not None:
            raise self.error
        return RecordSearchHitContract(
            hits=tuple(
                RecordSearchHitItem(
                    record_id=record_id,
                    record_type="knowledge",
                    authority="proposed",
                    sources=("lexical",),
                    revised_at="2026-11-14T12:00:00Z",
                    rank=index + 1,
                )
                for index, record_id in enumerate(self.record_ids)
            ),
            pending_changes=self.pending,
            semantic_state="absent",
        )


class SpyHandler[TAction, TResult](IHandler[TAction, TResult]):
    """Wraps a real handler: records each call's idempotency key, and fails on chosen keys once."""

    def __init__(self, inner: IHandler[Any, TResult]) -> None:
        self._inner: IHandler[Any, TResult] = inner
        self.keys: list[str] = []
        self.fail_once: dict[str, Exception] = {}

    async def handle(self, action: TAction) -> TResult:
        key: str = str(getattr(action, "idempotency_key", ""))
        self.keys.append(key)
        error: Exception | None = self.fail_once.pop(key, None)
        if error is not None:
            raise error
        return await self._inner.handle(action)


@dataclass(slots=True)
class CurationEnv:
    """The curation handlers wired over the in-memory store, with the doubles exposed."""

    base: ReviewEnv
    inbox: InMemoryCurationInbox
    curator: FakeCurator
    finder: FakeRelatedFinder
    experience: SpyHandler[CaptureExperienceCommand, CaptureResultDto]
    knowledge: SpyHandler[CaptureKnowledgeCommand, CaptureResultDto]
    revise: SpyHandler[ReviseKnowledgeCommand, ReviseResultDto]
    assertion: SpyHandler[ProposeAssertionCommand, ProposeAssertionResultDto] | None
    runner: CurationRunner
    ingest: IngestWorkBriefHandler
    apply: ApplyCurationHandler
    retry: RetryParkedCurationHandler
    list_parked: ListParkedCurationsHandler
    sleeps: list[float] = field(default_factory=list)

    def ingest_command(self, **overrides: Any) -> IngestWorkBriefCommand:
        """An ingest command for the fixture brief in the default space (lookup off by default)."""
        fields: dict[str, Any] = {
            "brief": brief_contract(),
            "space_key": DEFAULT_SPACE_KEY,
            "related_lookup": "off",
            **overrides,
        }
        return IngestWorkBriefCommand(**fields)

    def apply_command(
        self, candidates: Sequence[CurationCandidate], **overrides: Any
    ) -> ApplyCurationCommand:
        """An apply command for the fixture project and session."""
        fields: dict[str, Any] = {
            "space_key": DEFAULT_SPACE_KEY,
            "candidates": tuple(candidates),
            "project_key": PROJECT,
            "session": "sess-c7-0002",
            "actor": AGENT,
            **overrides,
        }
        return ApplyCurationCommand(**fields)


async def make_curation_env(
    *,
    answer: Sequence[CurationCandidate] = ANSWER_EK,
    assertions: bool = True,
    finder: FakeRelatedFinder | None = None,
    curator: FakeCurator | None = None,
    step_hook: StepHook | None = None,
) -> CurationEnv:
    """A fresh initialised store with the curation handlers over it."""
    base: ReviewEnv = await make_review_env()
    inbox = InMemoryCurationInbox(base.clock)
    the_curator: FakeCurator = curator or FakeCurator(answer)
    the_finder: FakeRelatedFinder = finder or FakeRelatedFinder()
    experience_spy = SpyHandler[CaptureExperienceCommand, CaptureResultDto](
        base.base.capture_experience
    )
    knowledge_spy = SpyHandler[CaptureKnowledgeCommand, CaptureResultDto](
        base.base.capture_knowledge
    )
    revise_spy = SpyHandler[ReviseKnowledgeCommand, ReviseResultDto](base.base.revise_knowledge)
    assertion_spy = (
        SpyHandler[ProposeAssertionCommand, ProposeAssertionResultDto](base.propose_assertion())
        if assertions
        else None
    )
    sleeps: list[float] = []
    runner = CurationRunner(
        inbox=inbox,
        curator=the_curator,
        finder=the_finder,
        records=base.records,
        uow_factory=base.uow,
        manager=CurationProcessManager(
            capture_experience=experience_spy,
            capture_knowledge=knowledge_spy,
            revise_knowledge=revise_spy,
            propose_assertion=assertion_spy,
            step_hook=step_hook,
        ),
        register=RegisterCurationPlanHandler(
            uow_factory=base.uow, clock=base.clock, ids=base.ids, schema=base.schema
        ),
        policy=CurationAdmissionPolicy(assertions_available=assertions),
        retry_delay_seconds=0.5,
        sleep=_recording_sleep(sleeps),
    )
    return CurationEnv(
        base=base,
        inbox=inbox,
        curator=the_curator,
        finder=the_finder,
        experience=experience_spy,
        knowledge=knowledge_spy,
        revise=revise_spy,
        assertion=assertion_spy,
        runner=runner,
        ingest=IngestWorkBriefHandler(runner=runner),
        apply=ApplyCurationHandler(runner=runner, inbox=inbox),
        retry=RetryParkedCurationHandler(runner=runner),
        list_parked=ListParkedCurationsHandler(inbox=inbox, clock=base.clock),
        sleeps=sleeps,
    )


def _recording_sleep(sink: list[float]) -> Callable[[float], Awaitable[None]]:
    async def sleep(seconds: float) -> None:
        sink.append(seconds)

    return sleep
