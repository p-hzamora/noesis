"""MCP note repository and unit of work against a fake Obsidian MCP server."""

from pathlib import Path

import pytest
import yaml
from tests.support.fake_obsidian_mcp import FakeObsidianMcp, fake_obsidian_mcp, free_port
from tests.support.notes_support import a_note

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import NotePath
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FilesystemNoteRepositoryAdapter,
    FilesystemNotesUnitOfWorkAdapter,
    McpNoteRepositoryAdapter,
    McpNotesUnitOfWorkAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.exceptions import NoteStorageError
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

pytestmark = pytest.mark.integration

FIRST: str = "repos/demo/decisions/first-note.md"
SECOND: str = "repos/demo/decisions/second-note.md"


def _notes() -> list[Note]:
    return [a_note(slug="first-note"), a_note(slug="second-note")]


def _unit(
    url: str, mapper: NoteMapper | None = None
) -> tuple[McpNotesUnitOfWorkAdapter, McpNoteRepositoryAdapter]:
    repository = McpNoteRepositoryAdapter(
        ObsidianMcpClient(url, timeout_seconds=2),
        mapper or NoteMapper(YamlFrontmatterCodecAdapter()),
    )
    return McpNotesUnitOfWorkAdapter(repository), repository


def _closed_url() -> str:
    return f"http://127.0.0.1:{free_port()}/mcp/"


def _writes(server: FakeObsidianMcp) -> list[str]:
    return [arguments["path"] for tool, arguments in server.calls if tool == "vault_write"]


async def _commit(url: str, notes: list[Note], mapper: NoteMapper | None = None) -> None:
    unit, _ = _unit(url, mapper)
    async with unit as uow:
        for note in notes:
            await uow.notes.save(note)
        await uow.commit()


async def test_commit_sends_the_same_markdown_the_filesystem_writer_stores(tmp_path: Path) -> None:
    mapper = NoteMapper(YamlFrontmatterCodecAdapter())
    files: Path = tmp_path / "files"
    unit = FilesystemNotesUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(files, mapper))
    async with unit as uow:
        for note in _notes():
            await uow.notes.save(note)
        await uow.commit()

    served: Path = tmp_path / "served"
    served.mkdir()
    with fake_obsidian_mcp(served) as server:
        await _commit(server.url, _notes())

    assert _writes(server) == [FIRST, SECOND]  # staging order, relative paths
    for path in (FIRST, SECOND):
        assert (served / path).read_bytes() == (files / path).read_bytes()
    sent: dict[str, str] = {
        call[1]["path"]: call[1]["content"] for call in server.calls if call[0] == "vault_write"
    }
    assert sent[FIRST] == (files / FIRST).read_text(encoding="utf-8")


async def test_get_reads_an_existing_note_through_vault_read(tmp_path: Path) -> None:
    note: Note = a_note(slug="first-note")
    (tmp_path / FIRST).parent.mkdir(parents=True)
    (tmp_path / FIRST).write_text(
        NoteMapper(YamlFrontmatterCodecAdapter()).to_markdown(note), encoding="utf-8"
    )

    with fake_obsidian_mcp(tmp_path) as server:
        _, repository = _unit(server.url)
        loaded: Note | None = await repository.get(note.path)

    assert loaded is not None
    assert (loaded.title, loaded.sections, loaded.path) == (note.title, note.sections, note.path)
    assert server.calls == [("vault_read", {"path": FIRST})]


@pytest.mark.parametrize("folder_exists", [True, False], ids=["missing-file", "missing-folder"])
async def test_get_returns_none_when_the_note_is_absent(
    tmp_path: Path, folder_exists: bool
) -> None:
    if folder_exists:
        (tmp_path / FIRST).parent.mkdir(parents=True)
        (tmp_path / SECOND).write_text("# Other\n", encoding="utf-8")

    with fake_obsidian_mcp(tmp_path) as server:
        _, repository = _unit(server.url)
        loaded: Note | None = await repository.get(NotePath(value=FIRST))

    assert loaded is None
    assert server.calls == [
        ("vault_read", {"path": FIRST}),
        ("vault_list", {"path": "repos/demo/decisions"}),  # is the file really absent?
    ]


async def test_get_with_an_unreachable_server_raises_a_storage_error() -> None:
    _, repository = _unit(_closed_url())

    with pytest.raises(NoteStorageError) as raised:
        await repository.get(NotePath(value=FIRST))

    assert raised.value.error_code == "NOTES_102_NOTE_STORAGE_FAILED"
    assert raised.value.message.startswith(f"Cannot read {FIRST} through the Obsidian MCP:")
    assert raised.value.metadata == {"path": FIRST, "backend": "mcp"}
    assert any("NOESIS_OBSIDIAN_MCP_URL" in step for step in raised.value.next_steps)


async def test_get_of_a_listed_file_that_cannot_be_read_raises_a_storage_error(
    tmp_path: Path,
) -> None:
    (tmp_path / FIRST).parent.mkdir(parents=True)
    (tmp_path / FIRST).write_bytes(b"\xff\xfe not utf-8")  # listed, but vault_read errors

    with fake_obsidian_mcp(tmp_path) as server:
        _, repository = _unit(server.url)
        with pytest.raises(NoteStorageError):
            await repository.get(NotePath(value=FIRST))


async def test_get_of_an_answer_without_content_raises_a_storage_error(tmp_path: Path) -> None:
    with fake_obsidian_mcp(tmp_path, read_without_content=True) as server:
        _, repository = _unit(server.url)
        with pytest.raises(NoteStorageError):
            await repository.get(NotePath(value=FIRST))


async def test_a_staged_note_is_returned_by_get_without_any_mcp_call(tmp_path: Path) -> None:
    note: Note = a_note(slug="first-note")

    with fake_obsidian_mcp(tmp_path) as server:
        _, repository = _unit(server.url)
        await repository.save(note)
        loaded: Note | None = await repository.get(note.path)

    assert loaded is note
    assert server.calls == []


async def test_leaving_the_unit_without_commit_sends_nothing_and_clears_the_stage(
    tmp_path: Path,
) -> None:
    note: Note = a_note(slug="first-note")

    with fake_obsidian_mcp(tmp_path) as server:
        unit, repository = _unit(server.url)
        async with unit as uow:
            await uow.notes.save(note)
        loaded: Note | None = await repository.get(note.path)

    assert loaded is None  # no longer staged, and never written
    assert _writes(server) == []
    assert not (tmp_path / FIRST).exists()


async def test_a_mid_send_failure_reports_what_was_written_and_what_was_not(
    tmp_path: Path,
) -> None:
    with (
        fake_obsidian_mcp(tmp_path, fail_write_after=1) as server,
        pytest.raises(NoteStorageError) as raised,
    ):
        await _commit(server.url, _notes())

    error: NoteStorageError = raised.value
    assert error.message.startswith(
        "Wrote 1 of 2 note(s) through the Obsidian MCP before it failed:"
    )
    assert error.metadata == {"backend": "mcp", "written": [FIRST], "not_written": [SECOND]}
    assert error.next_steps
    assert (tmp_path / FIRST).is_file()
    assert not (tmp_path / SECOND).exists()
    assert _writes(server) == [FIRST, SECOND]  # stops at the failing note


@pytest.mark.parametrize("failure", ["unreachable", "rejecting"])
async def test_a_failure_before_any_write_reports_every_note_as_not_written(
    tmp_path: Path, failure: str
) -> None:
    with fake_obsidian_mcp(tmp_path, reject_writes=failure == "rejecting") as server:
        url: str = _closed_url() if failure == "unreachable" else server.url
        with pytest.raises(NoteStorageError) as raised:
            await _commit(url, _notes())

    assert raised.value.message.startswith("Cannot write 2 note(s) through the Obsidian MCP:")
    assert raised.value.metadata == {
        "backend": "mcp",
        "written": [],
        "not_written": [FIRST, SECOND],
    }
    assert not (tmp_path / FIRST).exists()


class _FailingMapper(NoteMapper):
    """Renders every note except `bad_slug`, which fails like a note that cannot be serialised."""

    def __init__(self, bad_slug: str, failure: str) -> None:
        super().__init__(YamlFrontmatterCodecAdapter())
        self._bad_slug: str = bad_slug
        self._failure: str = failure

    def to_markdown(self, note: Note, existing: str | None = None) -> str:
        if note.path.stem != self._bad_slug:
            return super().to_markdown(note, existing)
        match self._failure:
            case "value-error":
                raise ValueError("cannot be encoded")
            case "yaml-error":
                raise yaml.YAMLError("cannot be dumped")
            case _:
                return "  \n"


@pytest.mark.parametrize("failure", ["value-error", "yaml-error", "blank"])
async def test_pre_validation_failure_sends_nothing(tmp_path: Path, failure: str) -> None:
    mapper = _FailingMapper("second-note", failure)

    with fake_obsidian_mcp(tmp_path) as server, pytest.raises(NoteStorageError) as raised:
        await _commit(server.url, _notes(), mapper)

    assert _writes(server) == []  # not even the first, valid note
    assert raised.value.message.startswith(
        f"Refusing to send any note: {SECOND} cannot be rendered ("
    )
    assert raised.value.metadata == {
        "backend": "mcp",
        "written": [],
        "not_written": [FIRST, SECOND],
        "invalid": SECOND,
    }


async def test_exists_looks_at_the_stage_then_at_the_vault(tmp_path: Path) -> None:
    (tmp_path / FIRST).parent.mkdir(parents=True)
    (tmp_path / FIRST).write_text("# Plain\n", encoding="utf-8")

    with fake_obsidian_mcp(tmp_path) as server:
        _, repository = _unit(server.url)
        await repository.save(a_note(slug="second-note"))

        assert await repository.exists(NotePath(value=FIRST))
        assert await repository.exists(NotePath(value=SECOND))
        assert not await repository.exists(NotePath(value="repos/demo/decisions/none.md"))
