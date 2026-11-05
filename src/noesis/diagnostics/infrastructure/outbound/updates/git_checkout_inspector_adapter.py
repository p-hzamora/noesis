"""`ICheckoutInspector` backed by the `git` executable."""

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

from noesis.diagnostics.application.ports.updates import CheckoutSnapshot, ICheckoutInspector

ORIGIN: str = "origin"
MIN_STEP_SECONDS: float = 0.05


class GitCheckoutInspectorAdapter(ICheckoutInspector):
    """Compares a checkout with its origin; any failure reads as "unknown", never raises.

    The only write is the object-only fetch, used when origin's commit is not in the local
    object store: it adds objects but leaves HEAD, the working tree, `FETCH_HEAD` and every ref
    (including `refs/remotes/origin/*`, via the empty `--refmap=`) alone.
    """

    def __init__(self, *, timeout_seconds: float, git_bin: str = "git") -> None:
        """
        Args:
            timeout_seconds: Budget for the whole inspection, network steps included.
            git_bin: The `git` executable.
        """
        self._timeout_seconds: float = timeout_seconds
        self._git_bin: str = git_bin

    async def inspect(self, package_dir: Path) -> CheckoutSnapshot:
        """Snapshot of the checkout `package_dir` belongs to; fields it cannot read stay None."""
        try:
            deadline: float = asyncio.get_running_loop().time() + self._timeout_seconds
            return await self._inspect(package_dir, deadline)
        except Exception:  # the contract is "never raises"
            return CheckoutSnapshot()

    async def _inspect(self, package_dir: Path, deadline: float) -> CheckoutSnapshot:
        checkout: Path | None = await self._checkout_of(package_dir, deadline)
        if checkout is None:
            return CheckoutSnapshot()
        local_sha: str | None = await self._git(checkout, deadline, "rev-parse", "HEAD")
        branch: str | None = await self._git(
            checkout, deadline, "rev-parse", "--abbrev-ref", "HEAD"
        )
        status: str | None = await self._git(checkout, deadline, "status", "--porcelain")
        remote_url: str | None = await self._git(
            checkout, deadline, "config", "--get", f"remote.{ORIGIN}.url"
        )
        snapshot = CheckoutSnapshot(
            checkout=checkout,
            branch=branch,
            remote_url=remote_url,
            local_sha=local_sha,
            dirty=bool(status),
        )
        if not (remote_url and local_sha):
            return snapshot
        remote_branch, remote_sha = await self._remote_head(checkout, deadline)
        snapshot = snapshot.model_copy(
            update={"remote_branch": remote_branch, "remote_sha": remote_sha}
        )
        if not (remote_branch and remote_sha) or remote_sha == local_sha:
            return snapshot
        if not await self._has_commit(checkout, deadline, remote_sha):
            await self._git(
                checkout, deadline,
                "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--refmap=", ORIGIN, remote_branch,
            )  # fmt: skip
        return snapshot.model_copy(
            update={
                "remote_contains_local": await self._is_ancestor(
                    checkout, deadline, local_sha, remote_sha
                ),
                "local_contains_remote": await self._is_ancestor(
                    checkout, deadline, remote_sha, local_sha
                ),
            }
        )

    async def _checkout_of(self, package_dir: Path, deadline: float) -> Path | None:
        """The repository root, only when `package_dir` is the `src/noesis` of that checkout.

        A package installed inside some other repository (a project's `.venv`) is not a checkout.
        """
        if not package_dir.is_dir():
            return None
        top: str | None = await self._git(package_dir, deadline, "rev-parse", "--show-toplevel")
        if not top:
            return None
        root: Path = Path(top)
        return root if (root / "src" / "noesis").resolve() == package_dir.resolve() else None

    async def _remote_head(self, checkout: Path, deadline: float) -> tuple[str | None, str | None]:
        """Origin's default branch and its commit, from `ls-remote --symref origin HEAD`."""
        listing: str | None = await self._git(
            checkout, deadline, "ls-remote", "--symref", ORIGIN, "HEAD"
        )
        branch: str | None = None
        sha: str | None = None
        for line in (listing or "").splitlines():
            first, _, second = line.partition("\t")
            if first.startswith("ref: refs/heads/"):
                branch = first.removeprefix("ref: refs/heads/")
            elif second == "HEAD":
                sha = first
        return branch, sha

    async def _has_commit(self, checkout: Path, deadline: float, sha: str) -> bool:
        return (
            await self._git(checkout, deadline, "cat-file", "-e", f"{sha}^{{commit}}") is not None
        )

    async def _is_ancestor(
        self, checkout: Path, deadline: float, ancestor: str, descendant: str
    ) -> bool | None:
        """Whether `ancestor` is in `descendant`'s history; None when git cannot tell."""
        code: int | None = await self._run(
            checkout, deadline, "merge-base", "--is-ancestor", ancestor, descendant
        )
        return {0: True, 1: False}.get(code) if code is not None else None

    async def _git(self, cwd: Path, deadline: float, *args: str) -> str | None:
        """stdout of `git -C cwd args` when it succeeds, else None."""
        output: tuple[int, str] | None = await self._exec(cwd, deadline, *args)
        return output[1] if output is not None and output[0] == 0 else None

    async def _run(self, cwd: Path, deadline: float, *args: str) -> int | None:
        """Exit code of `git -C cwd args`, or None when it could not run or timed out."""
        output: tuple[int, str] | None = await self._exec(cwd, deadline, *args)
        return output[0] if output is not None else None

    async def _exec(self, cwd: Path, deadline: float, *args: str) -> tuple[int, str] | None:
        """(exit code, stripped stdout), or None on a missing git, an OS error or the deadline."""
        remaining: float = deadline - asyncio.get_running_loop().time()
        if remaining < MIN_STEP_SECONDS:
            return None
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                self._git_bin, "-C", str(cwd), *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                start_new_session=True,  # git's helper processes share its group, so one kill stops all
            )  # fmt: skip
            stdout, _ = await asyncio.wait_for(process.communicate(), remaining)
        except TimeoutError:
            if process is not None and process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.communicate()  # reaps the process and closes its pipes
            return None
        except OSError:
            return None
        return (
            process.returncode if process.returncode is not None else 1,
            stdout.decode("utf-8", errors="replace").strip(),
        )
