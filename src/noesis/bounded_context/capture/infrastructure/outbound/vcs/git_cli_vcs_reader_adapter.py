"""`IVcsReader` backed by the `git` executable."""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import RepositoryLocationDto
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, DiffSize, WorktreeHead

GIT_TIMEOUT_SECONDS: float = 10.0
GIT_DIR_NAME: str = ".git"
BRANCH_PREFIX: str = "refs/heads/"
UNBORN_SHA: str = "0" * 40


class GitCliVcsReaderAdapter(IVcsReader):
    """Runs read-only git commands; any failure reads as "unknown", never raises."""

    def __init__(self, repository_name: Callable[[Path], str], git_bin: str = "git") -> None:
        """
        Args:
            repository_name: Names a repository from its common directory. Injected so that
                the naming rule has one owner (`noesis.core.git_root`).
            git_bin: The git executable.
        """
        self._repository_name: Callable[[Path], str] = repository_name
        self._git_bin: str = git_bin

    async def _git(self, cwd: Path, *args: str) -> str | None:
        """stdout of `git -C cwd args`, or None on any failure."""
        try:
            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                self._git_bin, "-C", str(cwd), *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            stdout, _ = await asyncio.wait_for(process.communicate(), GIT_TIMEOUT_SECONDS)
        except OSError, TimeoutError:
            return None
        return stdout.decode("utf-8", errors="replace").strip() if process.returncode == 0 else None

    async def common_dir(self, cwd: Path) -> RepositoryLocationDto | None:
        """`git rev-parse --path-format=absolute --git-common-dir`, resolved.

        The root is the main worktree for a normal repository, the work tree for a submodule,
        and the repository folder for a bare one.
        """
        found: str | None = await self._git(
            cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        if not found:
            return None
        common: Path = Path(found).resolve()
        if common.name == GIT_DIR_NAME:
            root: Path = common.parent
        elif GIT_DIR_NAME in common.parts:  # a submodule's git dir lives under the parent's .git
            top: str | None = await self._git(cwd, "rev-parse", "--show-toplevel")
            root = Path(top).resolve() if top else common
        else:
            root = common
        return RepositoryLocationDto(
            common_dir=common, root=root, name=self._repository_name(common)
        )

    async def worktrees(self, common_dir: Path) -> list[WorktreeHead]:
        """`git worktree list --porcelain`, with each HEAD's commit time from one `git log`."""
        listing: str | None = await self._git(common_dir, "worktree", "list", "--porcelain")
        if not listing:
            return []
        entries: list[dict[str, str]] = [
            dict(line.partition(" ")[::2] for line in block.splitlines())
            for block in listing.split("\n\n")
            if block.strip()
        ]
        live: list[dict[str, str]] = [
            entry
            for entry in entries
            if "bare" not in entry and "prunable" not in entry
            and entry.get("HEAD", UNBORN_SHA) != UNBORN_SHA
        ]  # fmt: skip
        times: dict[str, datetime] = await self._commit_times(
            common_dir, sorted({entry["HEAD"] for entry in live})
        )
        return [
            WorktreeHead(
                path=str(Path(entry["worktree"]).resolve()),
                sha=entry["HEAD"],
                branch=entry.get("branch", "HEAD").removeprefix(BRANCH_PREFIX),
                committed_at=times[entry["HEAD"]],
            )
            for entry in live
            if entry["HEAD"] in times
        ]

    async def _commit_times(self, common_dir: Path, shas: list[str]) -> dict[str, datetime]:
        """Commit time of each sha, in one git call."""
        if not shas:
            return {}
        output: str = (
            await self._git(common_dir, "log", "--no-walk=unsorted", "--format=%H %ct", *shas) or ""
        )
        times: dict[str, datetime] = {}
        for row in output.splitlines():
            sha, _, seconds = row.partition(" ")
            if seconds.isdigit():
                times[sha] = datetime.fromtimestamp(int(seconds), tz=UTC)
        return times

    async def head_commit(self, root: Path) -> CommitRecord | None:
        """HEAD's hash, subject and numstat size."""
        sha: str | None = await self._git(root, "rev-parse", "HEAD")
        if not sha:
            return None
        subject: str = await self._git(root, "log", "-1", "--format=%s", sha) or ""
        return CommitRecord(
            sha=sha,
            subject=subject,
            size=_numstat(await self._git(root, "show", sha, "--numstat", "--format=") or ""),
        )

    async def branch(self, root: Path) -> str:
        """Current branch, or `Not recorded`."""
        return await self._git(root, "rev-parse", "--abbrev-ref", "HEAD") or "Not recorded"

    async def stat_lines(self, root: Path, shas: Sequence[str], *, limit: int) -> list[str]:
        """`git show --stat` lines of each commit, capped at `limit` in total."""
        lines: list[str] = []
        for sha in shas:
            lines += (await self._git(root, "show", "--stat", "--format=", sha) or "").splitlines()
        return lines[:limit]


def _numstat(output: str) -> DiffSize:
    """Files and changed lines from `--numstat` output (binary files count as a file only)."""
    files: int = 0
    lines: int = 0
    for row in output.splitlines():
        added, _, rest = row.partition("\t")
        removed: str = rest.partition("\t")[0]
        if rest:
            files += 1
            if added.isdigit() and removed.isdigit():
                lines += int(added) + int(removed)
    return DiffSize(files=files, lines=lines)
