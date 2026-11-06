"""Capture use cases: enable/disable, record a commit, flush, status and journal."""

from datetime import timedelta
from pathlib import Path
from typing import Self

import pytest
from tests.support.capture_support import (
    REPO,
    SESSION,
    START,
    FakeTranscripts,
    FakeVcs,
    InMemoryCaptureSessionRepository,
    InMemoryCaptureSessionTreeReader,
    InMemoryCaptureUnitOfWork,
    InMemoryJournal,
    RecordingPublisher,
    RecordingRepoRegistry,
    a_commit,
)
from tests.support.notes_support import FixedClock

from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeEnum,
    CaptureRunDto,
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
    NewCommitCandidateSpecification,
    OutsideDebounceSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId
from noesis.exceptions import CaptureSessionNotFoundError

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
        self.registry = RecordingRepoRegistry()
        recorder = CaptureJournalRecorder(journal=self.journal, clock=self.clock, trace=trace)

        self.open_units: int = 0
        self.most_open_units: int = 0

        def unit_of_work(session_id: SessionId) -> InMemoryCaptureUnitOfWork:
            return _TrackedUnitOfWork(self)

        self.enable = EnableCaptureHandler(
            uow_factory=unit_of_work, clock=self.clock, recorder=recorder, registry=self.registry
        )
        self.disable = DisableCaptureHandler(
            uow_factory=unit_of_work, clock=self.clock, recorder=recorder
        )
        self.record = RecordCommitHandler(
            uow_factory=unit_of_work,
            vcs=self.vcs,
            clock=self.clock,
            recorder=recorder,
            registry=self.registry,
            candidates=NewCommitCandidateSpecification(window_seconds=120),
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
        self.runs = ListCaptureRunsHandler(
            journal=self.journal, tree=InMemoryCaptureSessionTreeReader(self.repository)
        )

    async def on(self, mode: CaptureModeEnum | None = CaptureModeEnum.LIVE) -> None:
        await self.enable.handle(EnableCaptureCommand(session_id=SESSION, mode=mode))

    async def commit(
        self,
        sha: str = "a" * 40,
        *,
        files: int = 2,
        lines: int = 25,
        path: Path = REPO,
        branch: str = "main",
        hint: Path | None = None,
    ) -> CaptureOutcomeEnum:
        self.vcs.set_head(
            sha, path=path, branch=branch, files=files, lines=lines, at=self.clock.now()
        )
        return await self.hook(hint)

    async def hook(self, hint: Path | None = None) -> CaptureOutcomeEnum:
        command = RecordCommitCommand(session_id=SESSION, cwd=REPO, worktree_hint=hint)
        return (await self.record.handle(command)).outcome

    async def stop(self, *, final: bool = False) -> CaptureOutcomeEnum:
        command = FlushCaptureCommand(
            session_id=SESSION, transcript_path=Path("/t.jsonl"), final=final
        )
        return (await self.flush.handle(command)).outcome


class _TrackedUnitOfWork(InMemoryCaptureUnitOfWork):
    """Counts how many units of work are open at once."""

    def __init__(self, world: _World) -> None:
        super().__init__(world.repository)
        self._world: _World = world

    async def __aenter__(self) -> Self:
        self._world.open_units += 1
        self._world.most_open_units = max(self._world.most_open_units, self._world.open_units)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._world.open_units -= 1
        await self.rollback()


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
    assert await world.hook() is CaptureOutcomeEnum.NO_NEW_COMMIT  # HEAD did not move

    status = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert (status.enabled, status.mode, status.pending_commits, status.pending_lines) == (
        True,
        "dry-run",
        1,
        25,
    )
    assert world.journal.outcomes() == ["enabled", "marked", "no_new_commit"]


async def test_a_commit_outside_a_repository_is_reported() -> None:
    world = _World()
    await world.on()
    world.vcs.location = None

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


# --- idempotent enable and --parent (CVG-003) ---

WORKTREE = Path("/work/demo-feature")


async def test_a_repeat_enable_is_quiet_and_keeps_pending_work_and_the_cursor() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)
    await world.commit("a" * 40)
    await world.stop()
    await world.commit("b" * 40)
    before = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))

    await world.on(None)

    after = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert after == before
    assert (after.mode, after.pending_commits, after.last_handover_at is not None) == (
        "dry-run",
        1,
        True,
    )
    assert world.journal.outcomes().count("enabled") == 1  # the repeat is not journaled


async def test_an_explicit_other_mode_on_a_repeat_call_changes_the_mode() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)

    await world.on(CaptureModeEnum.LIVE)

    status = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert status.mode == "live"
    assert world.journal.outcomes() == ["enabled", "enabled"]


async def test_the_repeat_is_journaled_in_trace_mode() -> None:
    world = _World(trace=True)
    await world.on()

    await world.on(None)

    assert world.journal.outcomes() == ["enabled", "already_enabled"]


async def test_a_session_that_predates_repository_ids_adopts_one_without_losing_pending() -> None:
    world = _World()
    await world.on()
    world.repository.stored[SESSION].pending = (a_commit(),)  # as an older version left it

    await world.enable.handle(EnableCaptureCommand(session_id=SESSION, repo_id="demo-12345678"))

    status = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert (status.repo_id, status.pending_commits) == ("demo-12345678", 1)


async def test_a_child_has_its_own_state_inherits_the_mode_and_records_its_parent() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)
    await world.commit()

    child = await world.enable.handle(EnableCaptureCommand(session_id="child-1", parent_id=SESSION))

    assert (child.session_id, child.enabled, child.mode, child.parent_id) == (
        "child-1",
        True,
        "dry-run",
        SESSION,
    )
    assert child.pending_commits == 0  # own pending work, not the parent's
    parent = await world.status.handle(GetCaptureStatusQuery(session_id=SESSION))
    assert parent.pending_commits == 1


async def test_a_child_can_pick_its_own_mode() -> None:
    world = _World()
    await world.on(CaptureModeEnum.DRY_RUN)

    child = await world.enable.handle(
        EnableCaptureCommand(session_id="child-1", parent_id=SESSION, mode=CaptureModeEnum.LIVE)
    )

    assert child.mode == "live"


async def test_a_parent_that_was_never_switched_on_is_reported() -> None:
    world = _World()

    with pytest.raises(CaptureSessionNotFoundError):
        await world.enable.handle(EnableCaptureCommand(session_id="child-1", parent_id="ghost"))


async def test_the_parent_is_read_and_released_before_the_childs_state_opens() -> None:
    world = _World()
    await world.on()
    world.most_open_units = 0

    await world.enable.handle(EnableCaptureCommand(session_id="child-1", parent_id=SESSION))

    assert world.most_open_units == 1


# --- recording across worktrees (CVG-003) ---


async def test_a_commit_made_in_a_linked_worktree_is_recorded_with_its_branch() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, at=START - timedelta(days=3))  # main: HEAD is old
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)

    assert await world.hook() is CaptureOutcomeEnum.MARKED

    pending = world.repository.stored[SESSION].pending
    assert [(c.sha, c.branch, c.worktree) for c in pending] == [("b" * 40, "feat/x", str(WORKTREE))]
    assert world.repository.stored[SESSION].repository_path == str(REPO)


async def test_the_old_head_of_the_main_checkout_is_never_recorded() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, at=START - timedelta(days=3))

    assert await world.hook() is CaptureOutcomeEnum.NO_NEW_COMMIT
    assert world.repository.stored[SESSION].pending == ()


async def test_two_candidate_worktrees_record_nothing_and_are_journaled() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, path=REPO, at=START)
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)

    assert await world.hook() is CaptureOutcomeEnum.AMBIGUOUS_WORKTREE

    assert world.repository.stored[SESSION].pending == ()
    assert world.journal.outcomes() == ["enabled", "ambiguous_worktree"]


async def test_an_unrecorded_candidate_is_still_a_candidate_at_the_next_hook() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, path=REPO, at=START)
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)
    await world.hook()

    assert await world.hook(hint=WORKTREE) is CaptureOutcomeEnum.MARKED  # the hint settles it

    assert [c.sha for c in world.repository.stored[SESSION].pending] == ["b" * 40]
    # main's commit was not recorded and stays a candidate (still within the window)
    assert await world.hook(hint=REPO) is CaptureOutcomeEnum.MARKED


async def test_a_hint_inside_a_worktree_folder_picks_that_worktree() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, path=REPO, at=START)
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)

    assert await world.hook(hint=WORKTREE / "src") is CaptureOutcomeEnum.MARKED
    assert [c.worktree for c in world.repository.stored[SESSION].pending] == [str(WORKTREE)]


async def test_a_hint_that_names_no_candidate_does_not_settle_the_choice() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, path=REPO, at=START)
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)

    assert await world.hook(hint=Path("/elsewhere")) is CaptureOutcomeEnum.AMBIGUOUS_WORKTREE


async def test_the_baseline_follows_the_current_worktrees_and_drops_removed_ones() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, at=START - timedelta(days=3))
    world.vcs.set_head("b" * 40, path=WORKTREE, at=START - timedelta(days=3))
    await world.hook()
    assert set(world.repository.stored[SESSION].observed_heads) == {str(REPO), str(WORKTREE)}

    del world.vcs.heads[str(WORKTREE)]
    await world.hook()

    assert set(world.repository.stored[SESSION].observed_heads) == {str(REPO)}


async def test_a_commit_older_than_the_window_is_not_taken_for_the_one_that_just_ran() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, at=START - timedelta(seconds=300))

    assert await world.hook() is CaptureOutcomeEnum.NO_NEW_COMMIT


# --- flush and runs across worktrees and sub-agents (CVG-003) ---


async def test_the_brief_takes_repository_path_and_branch_from_the_recorded_commit() -> None:
    world = _World()
    await world.on()
    world.vcs.set_head("a" * 40, at=START - timedelta(days=3))
    world.vcs.set_head("b" * 40, path=WORKTREE, branch="feat/x", at=START)
    await world.hook()

    assert await world.stop() is CaptureOutcomeEnum.HANDED_OVER

    brief = world.live.briefs[0]
    assert (brief.repository, brief.repository_path, brief.branch) == (
        "demo",  # the main folder name, not "demo-feature"
        str(REPO),
        "feat/x",
    )
    assert brief.session_label == SESSION[:8]


async def test_a_pending_commit_recorded_before_branches_were_kept_falls_back_to_the_vcs_branch() -> (
    None
):
    world = _World()
    await world.on()
    world.repository.stored[SESSION].pending = (
        a_commit(),
    )  # no branch, as an older version left it
    world.repository.stored[SESSION].repository_path = str(REPO)

    await world.stop()

    assert world.live.briefs[0].branch == "main"


async def test_runs_can_merge_the_journals_of_the_child_sessions() -> None:
    world = _World()
    await world.on()
    await world.enable.handle(EnableCaptureCommand(session_id="child-1", parent_id=SESSION))
    await world.enable.handle(EnableCaptureCommand(session_id="child-2", parent_id="child-1"))
    world.clock.current = START + timedelta(seconds=5)
    await world.journal.append(
        SessionId(value="child-1"), CaptureRunDto(at="2026-10-30T12:00:05+00:00", outcome="marked")
    )

    own = await world.runs.handle(ListCaptureRunsQuery(session_id=SESSION))
    merged = await world.runs.handle(
        ListCaptureRunsQuery(session_id=SESSION, include_children=True)
    )

    assert (own.children, [run.session_id for run in own.runs]) == ((), [SESSION])
    assert merged.children == ("child-1", "child-2")  # grandchildren included
    assert {run.session_id for run in merged.runs} == {SESSION, "child-1", "child-2"}
    assert [run.at for run in merged.runs] == sorted(run.at for run in merged.runs)


async def test_a_cyclic_parent_chain_does_not_loop_forever() -> None:
    world = _World()
    await world.on()
    await world.enable.handle(EnableCaptureCommand(session_id="child-1", parent_id=SESSION))
    world.repository.stored[SESSION].parent_id = "child-1"  # a corrupt file

    merged = await world.runs.handle(
        ListCaptureRunsQuery(session_id=SESSION, include_children=True)
    )

    assert merged.children == ("child-1",)


# --- the repository registry is written by the commands, never by a query (CVG-003) ---


async def test_enable_registers_the_repository_it_was_given() -> None:
    world = _World()

    await world.enable.handle(
        EnableCaptureCommand(session_id=SESSION, repo_id="demo-12345678", repository_path=str(REPO))
    )
    await world.enable.handle(EnableCaptureCommand(session_id="other"))  # no repository known

    assert world.registry.registered == [("demo-12345678", REPO)]


async def test_a_failing_parent_check_registers_nothing() -> None:
    world = _World()

    with pytest.raises(CaptureSessionNotFoundError):
        await world.enable.handle(
            EnableCaptureCommand(
                session_id="child",
                parent_id="ghost",
                repo_id="demo-12345678",
                repository_path=str(REPO),
            )
        )

    assert world.registry.registered == []


async def test_record_commit_registers_the_repository_only_for_an_opted_in_session() -> None:
    world = _World()
    assert await world.commit() is CaptureOutcomeEnum.NOT_OPTED_IN
    assert world.registry.registered == []

    await world.on()
    world.vcs.set_head("b" * 40)
    await world.hook()

    assert [path for _, path in world.registry.registered] == [REPO]
    assert world.registry.registered[0][0].startswith("demo-")


# --- outcomes ---


async def test_the_same_commit_seen_in_a_second_worktree_is_already_pending_and_quiet() -> None:
    world = _World()
    await world.on()
    assert await world.commit("a" * 40) is CaptureOutcomeEnum.MARKED

    world.vcs.set_head("a" * 40, path=WORKTREE, branch="feat/x")  # a new worktree, same commit

    assert await world.hook() is CaptureOutcomeEnum.ALREADY_PENDING
    assert CaptureOutcomeEnum.ALREADY_PENDING.is_quiet
    assert world.journal.outcomes() == ["enabled", "marked"]  # a repeat is not journaled
    assert len(world.repository.stored[SESSION].pending) == 1


async def test_a_journal_entry_written_with_the_old_already_pending_outcome_is_still_listed() -> (
    None
):
    world = _World()
    await world.on()
    await world.journal.append(
        SessionId(value=SESSION),
        CaptureRunDto(at="2026-10-30T12:00:05+00:00", outcome="already_pending"),
    )

    runs = await world.runs.handle(ListCaptureRunsQuery(session_id=SESSION))

    assert [run.outcome for run in runs.runs] == ["enabled", "already_pending"]
