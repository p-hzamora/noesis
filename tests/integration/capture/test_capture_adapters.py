"""Transcript reader, git reader, publishers and journal against real files and processes."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.capture_support import START
from tests.support.git_support import add_worktree, commit, git, init_repo, isolate_git
from tests.support.notes_support import FixedClock, a_brief

from noesis.bounded_context.capture.application.dtos import CaptureRunDto, TranscriptSnapshotDto
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, DiffSize, SessionId
from noesis.bounded_context.capture.infrastructure.outbound.journal import (
    JsonlCaptureJournalAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.publishing import (
    BriefFiles,
    DetachedProcessWorkBriefPublisherAdapter,
    DryRunWorkBriefPublisherAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.transcript import (
    ClaudeCodeTranscriptReaderAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.vcs import GitCliVcsReaderAdapter
from noesis.core.git_root import find_common_dir, find_main_repository, repository_name

pytestmark = pytest.mark.integration


def _line(role: str, content: object) -> str:
    return json.dumps({"message": {"role": role, "content": content}}) + "\n"


def _tool(name: str, **tool_input: str) -> str:
    return _line("assistant", [{"type": "tool_use", "name": name, "input": tool_input}])


async def test_transcript_snapshot_reads_goal_work_and_excerpt_since_the_cursor(
    tmp_path: Path,
) -> None:
    transcript: Path = tmp_path / "t.jsonl"
    head: str = _line("user", "<command-name>/x</command-name>") + _line(
        "user", "make login faster"
    )
    transcript.write_text(head + _tool("Read", file_path="a.py") + "not json\n", encoding="utf-8")
    cursor: int = transcript.stat().st_size
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(_line("assistant", [{"type": "text", "text": "chose a TTL cache"}]))
        handle.write(_tool("Bash", command='git commit -m "a\n\nb"'))

    reader = ClaudeCodeTranscriptReaderAdapter()
    before: TranscriptSnapshotDto | None = await reader.read(transcript, since_offset=0)
    after: TranscriptSnapshotDto | None = await reader.read(transcript, since_offset=cursor)
    rewritten: TranscriptSnapshotDto | None = await reader.read(transcript, since_offset=10**9)

    assert before is not None and after is not None and rewritten is not None
    assert before.goal == after.goal == "make login faster"
    assert (after.has_real_work, after.excerpt) == (True, "A: chose a TTL cache")
    assert after.end_offset == transcript.stat().st_size
    assert rewritten.excerpt.startswith("U: make login faster")
    assert await reader.read(tmp_path / "missing.jsonl", since_offset=0) is None
    assert await reader.read(None, since_offset=0) is None


async def test_reads_only_count_edits_and_commits_as_work_and_the_excerpt_is_capped(
    tmp_path: Path,
) -> None:
    transcript: Path = tmp_path / "t.jsonl"
    transcript.write_text(
        _tool("Read", file_path="a")
        + _tool("Bash", command="git status")
        + "".join(_line("user", f"prompt {i} " + "w " * 300) for i in range(30)),
        encoding="utf-8",
    )

    snapshot = await ClaudeCodeTranscriptReaderAdapter().read(transcript, since_offset=0)

    assert snapshot is not None
    assert snapshot.has_real_work is False
    assert len(snapshot.excerpt) <= 4000


def _name(common: Path) -> str:
    return repository_name(common)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


async def test_git_reader_reports_root_head_size_branch_and_stat(tmp_path: Path) -> None:
    repo: Path = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x\n" * 3, encoding="utf-8")
    (repo / "b.bin").write_bytes(b"\x00\x01")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: first")
    (repo / "sub").mkdir()
    vcs = GitCliVcsReaderAdapter(repository_name=_name)

    location = await vcs.common_dir(repo / "sub")
    head: CommitRecord | None = await vcs.head_commit(repo)

    assert location is not None
    assert (location.root, location.name) == (repo.resolve(), "repo")
    assert head is not None
    assert (head.subject, head.size) == ("feat: first", DiffSize(files=2, lines=3))
    assert await vcs.branch(repo) == "main"
    assert any("a.py" in line for line in await vcs.stat_lines(repo, [head.sha], limit=15))
    assert await vcs.common_dir(tmp_path) is None
    assert await GitCliVcsReaderAdapter(_name, "no-such-git").common_dir(repo) is None


async def test_dry_run_publisher_stores_the_brief(tmp_path: Path) -> None:
    publisher = DryRunWorkBriefPublisherAdapter(files=BriefFiles(tmp_path), clock=FixedClock(START))

    publication = await publisher.publish(a_brief())

    assert publication.published and publication.reference
    assert json.loads(Path(publication.reference).read_text())["repository"] == "demo"


@pytest.mark.parametrize("setsid_supported", [True, False], ids=["posix_spawn", "popen_fallback"])
async def test_live_publisher_detaches_the_curator_and_captures_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setsid_supported: bool
) -> None:
    if not setsid_supported:

        def _no_setsid(*_args: object, **_kwargs: object) -> int:
            raise NotImplementedError("posix_spawn: setsid unavailable on this platform")

        monkeypatch.setattr(os, "posix_spawn", _no_setsid)
    fake: Path = tmp_path / "fake_noesis.py"
    fake.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'ok': True, 'argv': sys.argv[1:], 'guard': os.environ.get('NOESIS_HOOK')}))\n",
        encoding="utf-8",
    )
    publisher = DetachedProcessWorkBriefPublisherAdapter(
        files=BriefFiles(tmp_path / "briefs"),
        command=[sys.executable, str(fake)],
        environment={},
        clock=FixedClock(START),
    )

    publication = await publisher.publish(a_brief())

    assert publication.published and publication.reference
    result_file: Path = BriefFiles.result_of(Path(publication.reference))
    for _ in range(200):
        if result_file.stat().st_size:
            break
        await asyncio.sleep(0.02)
    result = json.loads(result_file.read_text())
    assert result["argv"] == [
        "notes",
        "curate",
        "--brief-file",
        publication.reference,
        "--json",
    ]
    assert result["guard"] == "1"


async def test_live_publisher_reports_a_command_that_cannot_start(tmp_path: Path) -> None:
    publisher = DetachedProcessWorkBriefPublisherAdapter(
        files=BriefFiles(tmp_path),
        command=[str(tmp_path / "missing")],
        environment={},
        clock=FixedClock(START),
    )

    publication = await publisher.publish(a_brief())

    assert publication.published is False
    assert "could not start" in publication.detail


async def test_journal_appends_and_attaches_curation_results(tmp_path: Path) -> None:
    journal = JsonlCaptureJournalAdapter(tmp_path / "journal")
    session_id = SessionId(value="s-1")
    brief_file: Path = tmp_path / "b.json"
    BriefFiles.result_of(brief_file).write_text('{"ok": true}', encoding="utf-8")

    await journal.append(session_id, CaptureRunDto(at="t1", outcome="marked"))
    await journal.append(
        session_id, CaptureRunDto(at="t2", outcome="handed_over", reference=str(brief_file))
    )
    with (tmp_path / "journal/s-1.jsonl").open("a") as handle:
        handle.write("garbage\n")

    runs = await journal.read(session_id)
    assert [(run.outcome, run.result) for run in runs] == [
        ("marked", None),
        ("handed_over", {"ok": True}),
    ]
    assert await journal.read(SessionId(value="other")) == []


# --- worktrees (CVG-003) ---


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """(main checkout, linked worktree, bare clone)."""
    isolate_git(monkeypatch)
    main = init_repo(tmp_path / "billing")
    linked = add_worktree(main, tmp_path / "billing-feature", "feat/x")
    return main, linked, init_repo(tmp_path / "origin.git", bare=True)


async def test_every_worktree_resolves_to_the_same_repository(
    world: tuple[Path, Path, Path],
) -> None:
    main, linked, bare = world
    vcs = GitCliVcsReaderAdapter(repository_name=_name)

    from_main = await vcs.common_dir(main)
    from_linked = await vcs.common_dir(linked)

    assert from_main is not None and from_linked == from_main
    assert (from_main.common_dir, from_main.root, from_main.name) == (
        main / ".git",
        main,
        "billing",
    )
    from_bare = await vcs.common_dir(bare)
    assert from_bare is not None
    assert (from_bare.common_dir, from_bare.root, from_bare.name) == (bare, bare, "origin.git")


async def test_the_adapter_and_core_agree_on_main_linked_bare_and_submodule_repositories(
    world: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    main, linked, bare = world
    inner = init_repo(tmp_path / "inner")
    git(main, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "lib")
    vcs = GitCliVcsReaderAdapter(repository_name=_name)

    for start in (main, linked, bare, main / "lib"):
        location = await vcs.common_dir(start)
        assert location is not None
        assert location.common_dir == find_common_dir(start)
        assert location.root == find_main_repository(start)
        assert location.name == repository_name(location.common_dir)


async def test_worktrees_lists_each_head_with_branch_and_commit_time(
    world: tuple[Path, Path, Path],
) -> None:
    main, linked, _ = world
    new_sha = commit(linked, "work.txt")
    vcs = GitCliVcsReaderAdapter(repository_name=_name)

    heads = {head.path: head for head in await vcs.worktrees(main / ".git")}

    assert set(heads) == {str(main), str(linked)}
    assert (heads[str(linked)].sha, heads[str(linked)].branch) == (new_sha, "feat/x")
    assert heads[str(main)].branch == "main"
    assert abs((datetime.now(UTC) - heads[str(linked)].committed_at).total_seconds()) < 60


async def test_a_bare_repository_has_no_worktree_heads(world: tuple[Path, Path, Path]) -> None:
    _, _, bare = world

    assert await GitCliVcsReaderAdapter(repository_name=_name).worktrees(bare) == []
