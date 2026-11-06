"""The commit hook against real git worktrees and real JSON state (the bug this ticket fixes)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.capture_support import InMemoryJournal
from tests.support.git_support import add_worktree, commit, init_repo, isolate_git

from noesis.bounded_context.capture.application.dtos import CaptureOutcomeEnum
from noesis.bounded_context.capture.application.handlers.commands import (
    EnableCaptureCommand,
    EnableCaptureHandler,
    RecordCommitCommand,
    RecordCommitHandler,
)
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.specifications import NewCommitCandidateSpecification
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.bounded_context.capture.infrastructure.outbound.persistence import (
    JsonFileCaptureSessionRepositoryAdapter,
    JsonFileCaptureUnitOfWorkAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.persistence.mappers import (
    CaptureSessionMapper,
)
from noesis.bounded_context.capture.infrastructure.outbound.registry import (
    JsonFileRepoRegistryAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.vcs import GitCliVcsReaderAdapter
from noesis.core.git_root import repository_name
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

pytestmark = pytest.mark.integration

SESSION = "demo-12345678-abcdef012345"


class _World:
    def __init__(self, tmp_path: Path) -> None:
        self.main: Path = init_repo(tmp_path / "demo")
        self.linked: Path = add_worktree(self.main, tmp_path / "demo-feature", "feat/x")
        self.state: Path = tmp_path / "state"
        self.journal = InMemoryJournal()
        mapper = CaptureSessionMapper()
        clock = SystemClockAdapter()
        recorder = CaptureJournalRecorder(journal=self.journal, clock=clock, trace=False)

        def unit_of_work(session_id: SessionId) -> JsonFileCaptureUnitOfWorkAdapter:
            return JsonFileCaptureUnitOfWorkAdapter(
                JsonFileCaptureSessionRepositoryAdapter(self.state, mapper),
                session_id,
                lock_timeout_seconds=2,
            )

        registry = JsonFileRepoRegistryAdapter(tmp_path / "repos.json", lock_timeout_seconds=1.0)
        self.enable = EnableCaptureHandler(
            uow_factory=unit_of_work, clock=clock, recorder=recorder, registry=registry
        )
        self.record = RecordCommitHandler(
            uow_factory=unit_of_work,
            vcs=GitCliVcsReaderAdapter(repository_name=repository_name),
            clock=clock,
            recorder=recorder,
            registry=registry,
            candidates=NewCommitCandidateSpecification(window_seconds=120),
        )
        self._uow: Callable[[SessionId], JsonFileCaptureUnitOfWorkAdapter] = unit_of_work

    async def on(self) -> None:
        await self.enable.handle(EnableCaptureCommand(session_id=SESSION))

    async def hook(self, cwd: Path, hint: Path | None = None) -> CaptureOutcomeEnum:
        command = RecordCommitCommand(session_id=SESSION, cwd=cwd, worktree_hint=hint)
        return (await self.record.handle(command)).outcome

    async def pending(self) -> list[tuple[str, str, str]]:
        async with self._uow(SessionId(value=SESSION)) as uow:
            session = await uow.sessions.get(SessionId(value=SESSION))
        assert session is not None
        return [(c.sha, c.branch, c.worktree) for c in session.pending]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    isolate_git(monkeypatch)
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2001-01-01T00:00:00+00:00")  # an old starting point
    built = _World(tmp_path)
    monkeypatch.delenv("GIT_COMMITTER_DATE")  # later commits are made "now"
    return built


async def test_a_commit_made_in_a_linked_worktree_is_recorded_when_the_hook_runs_in_main(
    world: _World,
) -> None:
    await world.on()
    await world.hook(world.main)  # the first hook seeds the baseline: nothing is new yet
    sha = commit(world.linked, "work.txt")

    outcome = await world.hook(world.main)  # the payload cwd is the main checkout (the old bug)

    assert outcome is CaptureOutcomeEnum.MARKED
    assert await world.pending() == [(sha, "feat/x", str(world.linked))]


async def test_the_old_head_of_main_is_not_recorded_by_a_hook_without_a_new_commit(
    world: _World,
) -> None:
    await world.on()

    assert await world.hook(world.main) is CaptureOutcomeEnum.NO_NEW_COMMIT
    assert await world.pending() == []


async def test_a_commit_in_main_is_still_recorded(world: _World) -> None:
    await world.on()
    await world.hook(world.main)
    sha = commit(world.main, "main.txt")

    assert await world.hook(world.linked) is CaptureOutcomeEnum.MARKED
    assert await world.pending() == [(sha, "main", str(world.main))]


async def test_commits_in_two_worktrees_are_ambiguous_until_the_command_names_one(
    world: _World,
) -> None:
    await world.on()
    await world.hook(world.main)
    commit(world.main, "main.txt")
    wt_sha = commit(world.linked, "work.txt")

    assert await world.hook(world.main) is CaptureOutcomeEnum.AMBIGUOUS_WORKTREE
    assert await world.pending() == []
    assert world.journal.outcomes(SESSION)[-1] == "ambiguous_worktree"

    assert await world.hook(world.main, hint=world.linked) is CaptureOutcomeEnum.MARKED
    assert [sha for sha, _, _ in await world.pending()] == [wt_sha]


async def test_a_commit_older_than_the_window_is_ignored(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    await world.on()
    await world.hook(world.main)
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2001-01-01T00:00:00+00:00")
    commit(world.linked, "old.txt")

    assert await world.hook(world.main) is CaptureOutcomeEnum.NO_NEW_COMMIT
    assert await world.pending() == []
