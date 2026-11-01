"""`IVcsReader` backed by the `git` executable."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.domain.value_objects import CommitRecord, DiffSize

GIT_TIMEOUT_SECONDS: float = 10.0


class GitCliVcsReaderAdapter(IVcsReader):
    """Runs read-only git commands; any failure reads as "unknown", never raises."""

    def __init__(self, git_bin: str = "git") -> None:
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

    async def repository_root(self, cwd: Path) -> Path | None:
        """`git rev-parse --show-toplevel`."""
        top: str | None = await self._git(cwd, "rev-parse", "--show-toplevel")
        return Path(top) if top else None

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
