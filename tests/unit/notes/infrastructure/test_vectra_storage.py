"""vectra: the client runs the program; the storage adapters read and write through it."""

import json
import stat
from pathlib import Path

import pytest
from tests.support.notes_support import InMemoryNoteReadRepository, a_note, a_summary

from noesis.bounded_context.notes.domain.value_objects import NoteId, NoteScope
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FilesystemNoteRepositoryAdapter,
    VectraNoteReadRepositoryAdapter,
    VectraNoteRepositoryAdapter,
    VectraNotesUnitOfWorkAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.bounded_context.notes.infrastructure.outbound.vectra import (
    VectraCliClient,
    VectraClientError,
    VectraHit,
)
from noesis.exceptions import NoteStorageError
from noesis.shared_kernel.enums import SearchEngineEnum

pytestmark = pytest.mark.unit

A = "repos/demo/decisions/a.md"
B = "repos/demo/decisions/b.md"
ENVELOPE: dict[str, object] = {
    "ok": True,
    "result": {
        "collection": "notes",
        "query": "cache",
        "hits": [
            {"rank": 2, "path": B, "score": 0.5},
            {"rank": 1, "path": A, "score": 0.9},
        ],
    },
}


def _fake_vectra(tmp_path: Path, body: str) -> str:
    script: Path = tmp_path / "vectra"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _client(vectra_bin: str, timeout: float = 5.0) -> VectraCliClient:
    return VectraCliClient(vectra_bin=vectra_bin, timeout_seconds=timeout)


class _ScriptedClient(VectraCliClient):
    def __init__(self, *hits: VectraHit, fail: bool = False) -> None:
        super().__init__(vectra_bin="vectra", timeout_seconds=1)
        self.hits: tuple[VectraHit, ...] = hits
        self.fail: bool = fail
        self.searches: list[tuple[str, str, int]] = []
        self.syncs: list[tuple[str, Path]] = []

    async def search(
        self, collection: str, query: str, top_k: int, *, path_prefix: str | None = None
    ) -> tuple[VectraHit, ...]:
        self.searches.append((collection, query, top_k))
        if self.fail:
            raise VectraClientError("down")
        return self.hits[:top_k]

    async def sync(self, collection: str, root: Path) -> None:
        self.syncs.append((collection, root))
        if self.fail:
            raise VectraClientError("down")


# --- client ---------------------------------------------------------------------------------


def test_the_client_builds_search_and_sync_commands() -> None:
    client = _client("vectra")

    assert client.search_command("notes", "a cache", 3) == [
        "vectra", "search", "notes", "a cache", "--top-k", "3", "--json",
    ]  # fmt: skip
    assert client.search_command("notes", "q", 3, path_prefix="repos/demo")[-2:] == [
        "--path-prefix",
        "repos/demo",
    ]
    assert client.sync_command("notes", Path("/vault")) == [
        "vectra", "sync", "notes", "/vault", "--json",
    ]  # fmt: skip


async def test_the_client_returns_hits_with_scores_best_first(tmp_path: Path) -> None:
    binary: str = _fake_vectra(tmp_path, f"echo '{json.dumps(ENVELOPE)}'")

    hits = await _client(binary).search("notes", "cache", 5)

    assert [(hit.rank, hit.path, hit.score) for hit in hits] == [(1, A, 0.9), (2, B, 0.5)]


@pytest.mark.parametrize(
    "body",
    ["exit 1", "echo not-json", "echo '{\"ok\": false}'", 'echo \'{"result": {"hits": 3}}\''],
)
async def test_the_client_reports_a_failing_or_unreadable_answer(tmp_path: Path, body: str) -> None:
    with pytest.raises(VectraClientError):
        await _client(_fake_vectra(tmp_path, body)).search("notes", "cache", 5)


async def test_the_client_reports_a_missing_executable_and_a_timeout(tmp_path: Path) -> None:
    with pytest.raises(VectraClientError):
        await _client(str(tmp_path / "nope")).sync("notes", tmp_path)
    with pytest.raises(VectraClientError):
        await _client(_fake_vectra(tmp_path, "exec sleep 5"), timeout=0.2).search("n", "q", 1)


# --- read repository ------------------------------------------------------------------------


async def test_search_resolves_hits_to_notes_of_the_scope() -> None:
    a = a_summary(A, scope="repo:demo")
    b = a_summary(B, scope="repo:other")
    client = _ScriptedClient(
        VectraHit(rank=1, path=A, score=0.9), VectraHit(rank=2, path=B, score=0.5)
    )
    reader = VectraNoteReadRepositoryAdapter(
        client=client, collection="notes", files=InMemoryNoteReadRepository([a, b])
    )

    everything = await reader.search("cache", scope=None, limit=5)
    demo_only = await reader.search("cache", scope=NoteScope.parse("repo:demo"), limit=5)

    assert [note.path for note in everything.notes] == [A, B]
    assert everything.backend is SearchEngineEnum.VECTRA
    assert [note.path for note in demo_only.notes] == [A]
    assert client.searches[0] == ("notes", "cache", 15)  # over-fetched for the scope filter


async def test_search_skips_paths_that_are_not_notes() -> None:
    client = _ScriptedClient(VectraHit(rank=1, path="README.md", score=0.9))
    reader = VectraNoteReadRepositoryAdapter(
        client=client, collection="notes", files=InMemoryNoteReadRepository([a_summary(A)])
    )

    assert (await reader.search("cache", scope=None, limit=5)).notes == ()


async def test_search_reports_vectra_failure_as_a_storage_error() -> None:
    reader = VectraNoteReadRepositoryAdapter(
        client=_ScriptedClient(fail=True), collection="notes", files=InMemoryNoteReadRepository([])
    )

    with pytest.raises(NoteStorageError):
        await reader.search("cache", scope=None, limit=5)


async def test_lookups_read_the_collection_folder() -> None:
    note = a_summary(A)
    reader = VectraNoteReadRepositoryAdapter(
        client=_ScriptedClient(fail=True),
        collection="notes",
        files=InMemoryNoteReadRepository([note]),
    )

    assert await reader.find_by_id(NoteId(value=note.id), scope=None) == note
    assert [n.path for n in await reader.list_notes(scope=None, origin=None)] == [A]
    assert (await reader.read_note(A, scope=None)).path == A


# --- write repository -----------------------------------------------------------------------


def _repository(
    tmp_path: Path, client: _ScriptedClient, failures: list[str]
) -> VectraNoteRepositoryAdapter:
    return VectraNoteRepositoryAdapter(
        files=FilesystemNoteRepositoryAdapter(tmp_path, NoteMapper(YamlFrontmatterCodecAdapter())),
        client=client,
        collection="notes",
        root=tmp_path,
        on_sync_failure=lambda error: failures.append(str(error)),
    )


async def test_commit_writes_the_files_then_syncs_the_collection(tmp_path: Path) -> None:
    client = _ScriptedClient()
    note = a_note()
    failures: list[str] = []

    async with VectraNotesUnitOfWorkAdapter(_repository(tmp_path, client, failures)) as uow:
        await uow.notes.save(note)
        assert client.syncs == []
        await uow.commit()

    assert (tmp_path / note.path.value).is_file()
    assert client.syncs == [("notes", tmp_path)]
    assert failures == []


async def test_a_failed_sync_keeps_the_files_and_is_reported(tmp_path: Path) -> None:
    note = a_note()
    failures: list[str] = []

    async with VectraNotesUnitOfWorkAdapter(
        _repository(tmp_path, _ScriptedClient(fail=True), failures)
    ) as uow:
        await uow.notes.save(note)
        await uow.commit()

    assert (tmp_path / note.path.value).is_file()
    assert failures == ["down"]


async def test_leaving_without_commit_writes_and_syncs_nothing(tmp_path: Path) -> None:
    client = _ScriptedClient()
    repository = _repository(tmp_path, client, [])

    async with VectraNotesUnitOfWorkAdapter(repository) as uow:
        await uow.notes.save(a_note())

    assert await repository.exists(a_note().path) is False
    assert client.syncs == []
