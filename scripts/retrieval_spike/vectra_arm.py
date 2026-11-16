"""Prototype semantic projection, option A: one file per revision, indexed by `vectra sync`.

Layout (spec 30, "Projections"): `<state_dir>/index/<space>/<record_id>/r<revision>.md`; a hit's
path decodes to a `ProjectionKey`. The cursor is a local JSON file beside the directory
(`<state_dir>/index/<space>.cursor.json`). The writer only touches files; `vectra sync` runs when
the cursor advances (after each batch of the synchroniser, once for a whole rebuild), so the
cursor never claims more than Vectra holds.

Vectra runs from its own tool environment with a temporary HOME/XDG and `--env-file`; the
user's `~/.config/vectra` and `~/.local/share/vectra` are never read or written.
"""

# ruff: noqa: S101

import asyncio
import fcntl
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
    RankedCandidatesDto,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_cursor_store import (
    IIndexCursorStore,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    IIndexWriter,
    ProjectionEntryDto,
)
from noesis.bounded_context.retrieval.domain.enums import CandidateKindEnum
from noesis.bounded_context.retrieval.domain.value_objects import ProjectionKey
from noesis.shared_kernel.domain import JsonValue

VECTRA_BIN: Final[str] = "/home/phzamora/.local/share/uv/tools/vectra/bin/vectra"
VECTRA_PYTHON: Final[str] = "/home/phzamora/.local/share/uv/tools/vectra/bin/python"
HELPER: Final[Path] = Path(__file__).resolve().parent / "vectra_search_helper.py"
HF_HOME: Final[str] = "/home/phzamora/.cache/huggingface"
KIND: Final[str] = "semantic"
NO_REVISION_FILE: Final[str] = "r0.md"  # a record type without revisions (Experience)


def document_text(title: str | None, body: str) -> str:
    """The embedded text of one record: title and body, with no heading syntax."""
    return f"{title}\n\n{body}" if title else body


@dataclass(slots=True)
class VectraSettings:
    """Where a Vectra instance lives and which model it embeds with."""

    workdir: Path
    model_id: str
    dimension: int = 384

    @property
    def state_dir(self) -> Path:
        """Stand-in for Noesis's `<state_dir>`."""
        return self.workdir / "state"

    @property
    def vectra_home(self) -> Path:
        """Temporary HOME of every Vectra process."""
        return self.workdir / "vectra-home"

    @property
    def data_dir(self) -> Path:
        """Vectra's vector store (LanceDB)."""
        return self.workdir / "vectra-data"

    @property
    def env_file(self) -> Path:
        """Temporary `--env-file` carrying the model and data dir."""
        return self.workdir / "vectra.env"

    def prepare(self) -> None:
        """Create the directories and the temporary env file."""
        for folder in (self.state_dir, self.vectra_home, self.data_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text(
            f"VECTRA_EMBEDDING_MODEL_ID={self.model_id}\n"
            f"VECTRA_EMBEDDING_DIMENSION={self.dimension}\n"
            f"VECTRA_DATA_DIR={self.data_dir}\n",
            encoding="utf-8",
        )

    def space_dir(self, space_id: str) -> Path:
        """`<state_dir>/index/<space>`: the collection's root."""
        return self.state_dir / "index" / space_id

    def collection(self, space_id: str) -> str:
        """Vectra collection name of a space."""
        return f"noesis-{space_id.lower()}"

    def process_env(self) -> dict[str, str]:
        """A minimal environment for `vectra`: temporary HOME/XDG, the real HF cache."""
        return {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "HOME": str(self.vectra_home),
            "XDG_CONFIG_HOME": str(self.vectra_home / ".config"),
            "XDG_DATA_HOME": str(self.vectra_home / ".local/share"),
            "XDG_STATE_HOME": str(self.vectra_home / ".local/state"),
            "HF_HOME": HF_HOME,
        }


class VectraCliError(RuntimeError):
    """`vectra` exited non-zero."""


async def run_vectra(
    settings: VectraSettings, *args: str, timeout: float = 900.0
) -> dict[str, object]:
    """Run `vectra --env-file <temp> <args> --json` and return its `result`."""
    process = await asyncio.create_subprocess_exec(
        VECTRA_BIN,
        "--env-file",
        str(settings.env_file),
        *args,
        "--json",
        env=settings.process_env(),
        cwd=settings.vectra_home,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    text = stdout.decode("utf-8", "replace")
    if process.returncode != 0:
        raise VectraCliError(
            f"vectra {' '.join(args)} exit {process.returncode}: {text[:400]} {stderr.decode()[:400]}"
        )
    envelope = json.loads(text)
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


@dataclass(slots=True)
class FlushState:
    """Shared by writer and cursor store: files changed since the last `vectra sync`."""

    settings: VectraSettings
    dirty_spaces: set[str] = field(default_factory=set)
    sync_seconds: list[float] = field(default_factory=list)

    async def flush(self, space_id: str) -> None:
        """`vectra sync` the space's folder when files changed; raise when any file failed."""
        if space_id not in self.dirty_spaces:
            return
        root = self.settings.space_dir(space_id)
        root.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        result = await run_vectra(
            self.settings,
            "sync",
            self.settings.collection(space_id),
            str(root),
            "--allow-mass-delete",
        )
        self.sync_seconds.append(time.perf_counter() - started)
        failed = result.get("failed")
        if failed:
            raise VectraCliError(f"vectra sync failed for {failed}")
        self.dirty_spaces.discard(space_id)


def _decode(path: str) -> ProjectionKey | None:
    """`<record_id>/r<revision>.md` to a key; `r0.md` means a record without revisions."""
    parts = Path(path).parts
    if len(parts) < 2 or not parts[-1].startswith("r") or not parts[-1].endswith(".md"):
        return None
    number = parts[-1][1:-3]
    if not number.isdigit():
        return None
    return ProjectionKey(record_id=parts[-2], revision=int(number) or None)


class VectraIndexWriter(IIndexWriter):
    """Writes one file per record revision; replaces the record's other revisions."""

    def __init__(self, flush: FlushState) -> None:
        self._flush: FlushState = flush
        self._settings: VectraSettings = flush.settings

    @property
    def kind(self) -> str:
        """Projection name."""
        return KIND

    async def upsert(self, entry: ProjectionEntryDto) -> None:
        """Write `r<revision>.md` and remove the record's other revision files."""
        folder = self._settings.space_dir(entry.space_id) / entry.key.record_id
        folder.mkdir(parents=True, exist_ok=True)
        name = f"r{entry.key.revision}.md" if entry.key.revision is not None else NO_REVISION_FILE
        target = folder / name
        temporary = folder / f".{name}.tmp"
        temporary.write_text(document_text(entry.record.title, entry.record.body), encoding="utf-8")
        temporary.replace(target)
        for other in folder.glob("r*.md"):
            if other.name != name:
                other.unlink()
        self._flush.dirty_spaces.add(entry.space_id)

    async def clear(self, space_id: str) -> None:
        """Remove every file of the space; the next flush deletes them from Vectra."""
        root = self._settings.space_dir(space_id)
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        self._flush.dirty_spaces.add(space_id)

    def profile(self) -> dict[str, JsonValue]:
        """Model and layout the index was built with."""
        return {
            "store": "vectra",
            "layout": "option-a",
            "model_id": self._settings.model_id,
            "dimension": self._settings.dimension,
        }

    async def entries(self, space_id: str) -> dict[str, int | None]:
        """Record id to the revision of its file."""
        found: dict[str, int | None] = {}
        for path in self._settings.space_dir(space_id).glob("*/r*.md"):
            key = _decode(f"{path.parent.name}/{path.name}")
            if key is not None:
                found[key.record_id] = key.revision
        return found


class VectraCandidateSource(ICandidateSource):
    """Answers with `vectra search`; hit paths decode to projection keys."""

    def __init__(self, settings: VectraSettings) -> None:
        self._settings: VectraSettings = settings

    @property
    def kind(self) -> CandidateKindEnum:
        """Always `semantic`."""
        return CandidateKindEnum.SEMANTIC

    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """Up to `limit` documents, best first."""
        try:
            result = await run_vectra(
                self._settings,
                "search",
                self._settings.collection(space_id),
                text,
                "--top-k",
                str(limit),
            )
        except (VectraCliError, TimeoutError) as error:
            raise CandidateSourceUnavailableError(str(error)) from error
        hits = result["hits"]
        assert isinstance(hits, list)
        keys = [key for hit in hits if (key := _decode(str(hit["path"]))) is not None]
        return RankedCandidatesDto(hits=tuple(keys))

    def profile(self) -> dict[str, JsonValue]:
        """Same as the writer's."""
        return {
            "store": "vectra",
            "layout": "option-a",
            "model_id": self._settings.model_id,
            "dimension": self._settings.dimension,
        }


class VectraHelperProcess:
    """A resident `vectra_search_helper.py` child (Vectra's interpreter, Vectra's own handlers)."""

    def __init__(self, settings: VectraSettings) -> None:
        self._settings: VectraSettings = settings
        self._process: asyncio.subprocess.Process | None = None
        self.ready: dict[str, object] = {}

    async def start(self) -> None:
        """Start the helper and wait for its ready line."""
        self._process = await asyncio.create_subprocess_exec(
            VECTRA_PYTHON,
            "-I",
            str(HELPER),
            str(self._settings.env_file),
            env=self._settings.process_env(),
            cwd=self._settings.vectra_home,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=1 << 24,
        )
        assert self._process.stdout is not None
        self.ready = json.loads(await self._process.stdout.readline())

    async def search(self, collection: str, text: str, top_k: int) -> dict[str, object]:
        """Vectra's own search handler result for one query: paths in rank order."""
        if self._process is None:
            await self.start()
        assert self._process is not None
        assert self._process.stdin is not None and self._process.stdout is not None
        request = {"op": "search", "collection": collection, "text": text, "top_k": top_k}
        self._process.stdin.write((json.dumps(request) + "\n").encode())
        await self._process.stdin.drain()
        reply = json.loads(await self._process.stdout.readline())
        assert isinstance(reply, dict)
        return reply

    async def close(self) -> None:
        """Quit the helper."""
        if self._process is not None and self._process.returncode is None:
            assert self._process.stdin is not None
            self._process.stdin.write(b'{"op": "quit"}\n')
            await self._process.stdin.drain()
            self._process.stdin.close()
            await self._process.wait()


class VectraHelperCandidateSource(ICandidateSource):
    """Same ranking as `VectraCandidateSource`, answered by the resident helper (no per-call load)."""

    def __init__(self, settings: VectraSettings, helper: VectraHelperProcess) -> None:
        self._settings: VectraSettings = settings
        self._helper: VectraHelperProcess = helper

    @property
    def kind(self) -> CandidateKindEnum:
        """Always `semantic`."""
        return CandidateKindEnum.SEMANTIC

    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """Up to `limit` documents, best first."""
        reply = await self._helper.search(self._settings.collection(space_id), text, limit)
        if "error" in reply:
            raise CandidateSourceUnavailableError(str(reply["error"]))
        paths = reply["paths"]
        assert isinstance(paths, list)
        keys = [key for path in paths if (key := _decode(str(path))) is not None]
        return RankedCandidatesDto(hits=tuple(keys))

    def profile(self) -> dict[str, JsonValue]:
        """Same as the writer's."""
        return {
            "store": "vectra",
            "layout": "option-a",
            "model_id": self._settings.model_id,
            "dimension": self._settings.dimension,
        }


class FileCursorStore(IIndexCursorStore):
    """Local cursor file per space, a flock-guarded lock with a TTL, and the flush hook.

    `advance` first flushes pending files into Vectra, so the cursor is only ever behind.
    """

    def __init__(self, flush: FlushState) -> None:
        self._flush: FlushState = flush
        self._root: Path = flush.settings.state_dir / "index"

    def _path(self, projection: str, space_id: str) -> Path:
        return self._root / f"{space_id}.{projection}.cursor.json"

    def _read(self, projection: str, space_id: str) -> dict[str, object]:
        path = self._path(projection, space_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor; null when never written."""
        sequence = self._read(projection, space_id).get("sequence")
        return int(sequence) if isinstance(sequence, int) else None

    async def advance(self, projection: str, space_id: str, sequence: int) -> None:
        """Flush files to Vectra, then write the cursor atomically."""
        await self._flush.flush(space_id)
        self._update(projection, space_id, lambda state: state.update(sequence=sequence))

    def _update(self, projection: str, space_id: str, change: object) -> bool:
        path = self._path(projection, space_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / f"{path.name}.guard").open("a+") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            state = self._read(projection, space_id)
            assert callable(change)
            change(state)
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.replace(path)
        return True

    async def acquire(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Compare-and-set the lock under an exclusive file lock."""
        now = datetime.now(UTC)
        taken = False

        def take(state: dict[str, object]) -> None:
            nonlocal taken
            holder, expires = state.get("lock_owner"), state.get("lock_expires_at")
            if (
                holder not in (None, owner)
                and isinstance(expires, str)
                and datetime.fromisoformat(expires) > now
            ):
                return
            state["lock_owner"] = owner
            state["lock_expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat()
            taken = True

        self._update(projection, space_id, take)
        return taken

    async def release(self, projection: str, space_id: str, owner: str) -> None:
        """Drop the lock when `owner` holds it."""

        def drop(state: dict[str, object]) -> None:
            if state.get("lock_owner") == owner:
                state.pop("lock_owner", None)
                state.pop("lock_expires_at", None)

        self._update(projection, space_id, drop)
