"""Capture use cases: enable/disable, record a commit, flush, status and journal."""

from datetime import timedelta
from pathlib import Path

import pytest
from tests.support.capture_support import (
    REPO,
    SESSION,
    START,
    FakeTranscripts,
    FakeVcs,
    InMemoryCaptureSessionRepository,
    InMemoryCaptureUnitOfWork,
    InMemoryJournal,
    RecordingPublisher,
    a_commit,
)
from tests.support.knowledge_support import FixedClock

from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeEnum,
    TranscriptSnapshotDto,
)
from noesis.bounded_context.capture.application.handlers.commands import (
    DisableCaptureCommand,
    DisableCaptureHandler,
    EnableCaptureCommand,
    EnableCaptureHandler,
    FlushCaptureCommand,
    FlushCaptureHandler,
    RecordCommitCommand,
    RecordCommitHandler,
)
from noesis.bounded_context.capture.application.handlers.queries import (
    GetCaptureStatusHandler,
    GetCaptureStatusQuery,
    ListCaptureRunsHandler,
    ListCaptureRunsQuery,
)
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.application.services.publishing import (
    WorkBriefPublisherResolver,
)
from noesis.bounded_context.capture.domain.specifications import (
    OutsideDebounceSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId

pytestmark = pytest.mark.unit


class _World:
    def __init__(
        self, *, trace: bool = False, min_files: int = 2, min_lines: int = 20, fail: bool = False
    ) -> None:
        self.repository = InMemoryCaptureSessionRepository()
        self.clock = FixedClock(START)
        self.journal = InMemoryJournal()
        self.vcs = FakeVcs()
        self.transcripts = FakeTranscripts()
        self.live = RecordingPublisher(fail=fail)
        self.dry = RecordingPublisher()
        recorder = CaptureJournalRecorder(journal=self.journal, clock=self.clock, trace=trace)

        def unit_of_work(session_id: SessionId) -> InMemoryCaptureUnitOfWork:
            return InMemoryCaptureUnitOfWork(self.repository)

        self.enable = EnableCaptureHandler(
            uow_factory=unit_of_work, clock=self.clock, recorder=recorder
        )
        self.disable = DisableCaptureHandler(
            uow_factory=unit_of_work, clock=self.clock, recorder=recorder
        )
        self.record = RecordCommitHandler(
            uow_factory=unit_of_work, vcs=self.vcs, clock=self.clock, recorder=recorder
        )
        self.flush = FlushCaptureHandler(
            uow_factory=unit_of_work,
            transcripts=self.transcripts,
            vcs=self.vcs,
            publishers=WorkBriefPublisherResolver(
                {CaptureModeEnum.LIVE: self.live, CaptureModeEnum.DRY_RUN: self.dry}
            ),
            clock=self.clock,
            recorder=recorder,
            debounce=OutsideDebounceSpecification(300),
            significance=SignificantChangeSpecification(min_files=min_files, min_lines=min_lines),
        )
        self.status = GetCaptureStatusHandler(uow_factory=unit_of_work)
        self.runs = ListCaptureRunsHandler(journal=self.journal)

    async def on(self, mode: CaptureModeEnum = CaptureModeEnum.LIVE) -> None:
        await self.enable.handle(EnableCaptureCommand(session_id=SESSION, mode=mode))

    async def commit(
        self, sha: str = "a" * 40, *, files: int = 2, lines: int = 25
    ) -> CaptureOutcomeEnum:
        self.vcs.head = a_commit(sha, files=files, lines=lines)
        return (await self.record.handle(RecordCommitCommand(session_id=SESSION, cwd=REPO))).outcome

    async def stop(self, *, final: bool = False) -> CaptureOutcomeEnum:
        command = FlushCaptureCommand(
            session_id=SESSION, transcript_path=Path("/t.jsonl"), final=final
        )
        return (await self.flush.handle(command)).outcome


async def test_everything_is_off_until_switched_on() -> None:
    world = _World()

    assert await world.commit() is CaptureOutcomeEnum.NOT_OPTED_IN
    assert await world.stop() is CaptureOutcomeEnum.NOT_OPTED_IN
    assert world.journal.outcomes() == []  # quiet outcomes are not journaled
    status = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert (status.enabled, status.pending_commits) == (False, 0)


async def test_enable_record_and_status() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)

    assert await world.commit() is CaptureOutcomeEnum.MARKED
    assert await world.commit() is CaptureOutcomeEnum.ALREADY_PENDING

    status = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert (status.enabled, status.mode, status.pending_commits, status.pending_lines) == (
        True,
        "dry-run",
        1,
        25,
    )
    assert world.journal.outcomes() == ["enabled", "marked", "already_pending"]


async def test_a_commit_outside_a_repository_is_reported() -> None:
    world = _World()
    await world.on()
    world.vcs.root = None

    assert await world.commit() is CaptureOutcomeEnum.NOT_IN_REPO


async def test_flush_publishes_one_brief_for_all_pending_commits_and_moves_the_cursor() -> None:
    world = _World()
    await world.on()
    await world.commit("a" * 40, files=1, lines=10)
    await world.commit("b" * 40, files=1, lines=10)

    assert await world.stop() is CaptureOutcomeEnum.HANDED_OVER

    brief = world.live.briefs[0]
    assert [commit.sha for commit in brief.commits] == ["a" * 40, "b" * 40]
    assert (brief.repository, brief.repository_path, brief.branch, brief.head) == (
        "demo",
        "/work/demo",
        "main",
        "b" * 40,
    )
    assert brief.goal == "speed up login"
    assert brief.diff_stat == ("aaaaaaaa | 3 +++", "bbbbbbbb | 3 +++")
    assert await world.stop() is CaptureOutcomeEnum.NO_PENDING
    assert world.transcripts.offsets == [0]
    run = (await world.runs.handle(ListCaptureRunsQuery(session_id=SESSION))).runs[-1]
    assert (run.outcome, run.reference) == ("handed_over", "/briefs/1.json")


async def test_dry_run_mode_uses_the_dry_run_publisher() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)
    await world.commit()

    await world.stop()

    assert (len(world.dry.briefs), len(world.live.briefs)) == (1, 0)


async def test_debounce_keeps_work_pending_and_the_final_flush_ignores_it() -> None:
    world = _World()
    await world.on()
    await world.commit("a" * 40)
    await world.stop()
    await world.commit("b" * 40)
    world.clock.current = START + timedelta(seconds=10)

    assert await world.stop() is CaptureOutcomeEnum.DEBOUNCED
    assert await world.stop(final=True) is CaptureOutcomeEnum.HANDED_OVER
    assert world.transcripts.offsets == [0, 100]


async def test_trivial_work_stays_pending_at_stop_and_is_dropped_at_session_end() -> None:
    world = _World(min_files=3, min_lines=50)
    await world.on()
    await world.commit("a" * 40, files=1, lines=1)

    assert await world.stop() is CaptureOutcomeEnum.TRIVIAL
    assert (
        await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    ).pending_commits == 1
    assert await world.stop(final=True) is CaptureOutcomeEnum.TRIVIAL_DROPPED
    assert (
        await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    ).pending_commits == 0


async def test_small_commits_add_up_to_a_significant_change() -> None:
    world = _World(min_files=3, min_lines=50)
    await world.on()
    for sha in ("a", "b", "c"):
        await world.commit(sha * 40, files=1, lines=1)

    assert await world.stop() is CaptureOutcomeEnum.HANDED_OVER


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (None, CaptureOutcomeEnum.TRANSCRIPT_UNREADABLE),
        (
            TranscriptSnapshotDto(end_offset=5, has_real_work=False, goal="", excerpt=""),
            CaptureOutcomeEnum.NO_REAL_WORK,
        ),
    ],
)
async def test_the_transcript_must_be_readable_and_show_real_work(
    snapshot: TranscriptSnapshotDto | None, expected: CaptureOutcomeEnum
) -> None:
    world = _World()
    world.transcripts.snapshot = snapshot
    await world.on()
    await world.commit()

    assert await world.stop() is expected
    assert world.live.briefs == []


async def test_a_hand_over_that_cannot_start_is_retried_once_then_abandoned() -> None:
    world = _World(fail=True)
    await world.on()
    await world.commit()

    assert await world.stop() is CaptureOutcomeEnum.HANDOVER_FAILED
    assert await world.stop() is CaptureOutcomeEnum.HANDOVER_ABANDONED
    assert await world.stop() is CaptureOutcomeEnum.NO_PENDING


async def test_disable_stops_capture_and_trace_mode_journals_quiet_outcomes() -> None:
    world = _World(trace=True)
    await world.on()
    await world.disable.handle(DisableCaptureCommand(session_id=SESSION))

    assert await world.commit() is CaptureOutcomeEnum.NOT_OPTED_IN
    assert world.journal.outcomes() == ["enabled", "disabled", "not_opted_in"]
    status = await world.disable.handle(DisableCaptureCommand(session_id="never-on"))
    assert status.enabled is False
