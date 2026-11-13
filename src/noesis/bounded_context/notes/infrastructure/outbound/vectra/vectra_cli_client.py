"""Client of the `vectra` program: runs it and reads its JSON envelope.

The only place that knows vectra's command line. Storage adapters use it; nothing else runs
vectra.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


class VectraClientError(Exception):
    """vectra could not answer: not installed, too slow, failed, or printed something unreadable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class VectraHit:
    """One document of a vectra search, as vectra reports it.

    Attributes:
        rank: 1-based position, 1 is the best match.
        path: Path of the document, relative to the collection root.
        score: Similarity in 0..1.
    """

    rank: int
    path: str
    score: float


class VectraCliClient:
    """Runs `vectra ... --json`: semantic search, and sync of a folder into a collection.

    Args:
        vectra_bin: The `vectra` executable.
        timeout_seconds: Time limit for one run.
    """

    def __init__(self, *, vectra_bin: str, timeout_seconds: float) -> None:
        self._vectra_bin: str = vectra_bin
        self._timeout_seconds: float = timeout_seconds

    def search_command(
        self, collection: str, query: str, top_k: int, *, path_prefix: str | None = None
    ) -> list[str]:
        """The argument vector of one search."""
        command: list[str] = [
            self._vectra_bin, "search", collection, query,
            "--top-k", str(top_k), "--json",
        ]  # fmt: skip
        return [*command, "--path-prefix", path_prefix] if path_prefix else command

    def sync_command(self, collection: str, root: Path) -> list[str]:
        """The argument vector of one sync."""
        return [self._vectra_bin, "sync", collection, str(root), "--json"]

    async def sync(self, collection: str, root: Path) -> None:
        """Index the changes of `root` into `collection` (created on first use).

        Raises:
            VectraClientError: vectra is missing, timed out, or some file failed to index.
        """
        await self._run(self.sync_command(collection, root))

    async def search(
        self, collection: str, query: str, top_k: int, *, path_prefix: str | None = None
    ) -> tuple[VectraHit, ...]:
        """The best documents of `collection`, best first.

        Args:
            collection: Collection name.
            query: Natural-language query.
            top_k: Most documents to return.
            path_prefix: Only documents under this path of the collection root.

        Raises:
            VectraClientError: vectra is missing, timed out, failed or answered unreadably.
        """
        stdout: bytes = await self._run(
            self.search_command(collection, query, top_k, path_prefix=path_prefix)
        )
        try:
            envelope: object = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise VectraClientError("vectra did not print JSON.") from error
        result: object = envelope.get("result") if isinstance(envelope, dict) else None
        raw: object = result.get("hits") if isinstance(result, dict) else None
        if not isinstance(raw, list):
            raise VectraClientError("vectra printed an unexpected JSON shape.")
        hits: list[VectraHit] = []
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                rank: object = item.get("rank")
                score: object = item.get("score")
                hits.append(
                    VectraHit(
                        rank=rank if isinstance(rank, int) else len(hits) + 1,
                        path=item["path"],
                        score=float(score) if isinstance(score, int | float) else 0.0,
                    )
                )
        return tuple(sorted(hits, key=lambda hit: hit.rank))

    async def _run(self, command: list[str]) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as error:
            raise VectraClientError(f"Cannot start `{self._vectra_bin}`: {error}") from error
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), self._timeout_seconds)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise VectraClientError("vectra timed out.") from error
        if process.returncode != 0:
            raise VectraClientError(f"vectra exited with {process.returncode}.")
        return stdout
