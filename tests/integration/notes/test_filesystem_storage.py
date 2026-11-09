"""Filesystem note storage: mapper, repository, unit of work and read repository."""

from pathlib import Path

import pytest
from tests.support.notes_support import a_note

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import (
    NoteArea,
    NoteLocation,
    NoteOriginEnum,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FilesystemNoteReadRepositoryAdapter,
    FilesystemNoteRepositoryAdapter,
    FilesystemNotesUnitOfWorkAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.exceptions import NoteStorageError

pytestmark = pytest.mark.integration

MANUAL_NOTE: str = """---
type: gotcha
title: Clock skew breaks tokens
updated: 2026-01-05
---

# Clock skew breaks tokens

## Symptom

Tokens rejected right after login.
"""


@pytest.fixture
def mapper() -> NoteMapper:
    return NoteMapper()


async def test_committed_notes_are_written_as_markdown_and_read_back(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    note: Note = a_note()
    note.commits = ("8e6d3b5f",)
    note.session = "abcd1234"
    unit = FilesystemNotesUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(tmp_path, mapper))

    async with unit as uow:
        await uow.notes.save(note)
        await uow.commit()

    text: str = (tmp_path / "repos/demo/auto/decisions/use-ttl-cache.md").read_text(
        encoding="utf-8"
    )
    assert text.startswith("---\ntype: decision\nid: auto-decision-use-ttl-cache\nrepo: demo\n")
    assert "origin: auto" in text
    assert "date: 2026-10-30" in text
    assert "# Use a TTL cache\n\n## Decision\n\nKeep tokens in memory." in text
    loaded: Note | None = await FilesystemNoteRepositoryAdapter(tmp_path, mapper).get(note.location)
    assert loaded is not None
    assert (loaded.title, loaded.commits, loaded.session) == (
        note.title,
        note.commits,
        note.session,
    )
    assert loaded.sections == note.sections
    assert loaded.updated_at.date() == note.updated_at.date()


async def test_leaving_without_commit_writes_nothing(tmp_path: Path, mapper: NoteMapper) -> None:
    async with FilesystemNotesUnitOfWorkAdapter(
        FilesystemNoteRepositoryAdapter(tmp_path, mapper)
    ) as uow:
        await uow.notes.save(a_note())
        assert (
            await uow.notes.get(a_note().location) is not None
        )  # staged notes are visible inside the unit

    assert not any(tmp_path.rglob("*.md"))


async def test_hand_written_notes_without_required_sections_load(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    path: Path = tmp_path / "repos/demo/gotchas/clock-skew.md"
    path.parent.mkdir(parents=True)
    path.write_text(MANUAL_NOTE, encoding="utf-8")

    note: Note | None = await FilesystemNoteRepositoryAdapter(tmp_path, mapper).get(
        NoteLocation.parse("repos/demo/gotchas/clock-skew.md")
    )

    assert note is not None
    assert note.location.origin is NoteOriginEnum.MANUAL
    assert [section.heading for section in note.sections] == ["Symptom"]


async def test_read_repository_lists_filters_and_ranks_notes(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    manual: Path = tmp_path / "repos/demo/gotchas/clock-skew.md"
    manual.parent.mkdir(parents=True)
    manual.write_text(MANUAL_NOTE, encoding="utf-8")
    (tmp_path / "repos/demo/index.md").write_text("# index", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/decisions").mkdir()
    (tmp_path / ".obsidian/decisions/x.md").write_text("# hidden", encoding="utf-8")
    unit = FilesystemNotesUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(tmp_path, mapper))
    async with unit as uow:
        await uow.notes.save(a_note())
        await uow.commit()
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    everything = await reader.list_notes(area=None, origin=None)
    auto_only = await reader.list_notes(
        area=NoteArea.for_repository("demo"), origin=NoteOriginEnum.AUTO
    )
    found = (await reader.search("token clock", area=None, limit=5)).notes
    nothing = (await reader.search("a an", area=None, limit=5)).notes
    elsewhere = await reader.list_notes(area=NoteArea.for_repository("other"), origin=None)

    assert [note.path for note in everything] == [
        "repos/demo/auto/decisions/use-ttl-cache.md",
        "repos/demo/gotchas/clock-skew.md",
    ]
    assert [note.origin for note in auto_only] == ["auto"]
    assert found[0].path == "repos/demo/gotchas/clock-skew.md"
    assert found[0].snippet == "Tokens rejected right after login."
    assert (nothing, elsewhere) == ((), [])


def test_frontmatter_errors_are_tolerated(mapper: NoteMapper) -> None:
    parsed = mapper.parse("---\n: [unclosed\n---\n# Title\n\n## Cause\n\nx\n")

    assert parsed.frontmatter == {}
    assert parsed.title == "Title"


async def test_read_note_returns_the_whole_file_inside_the_area(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    (tmp_path / "repos/demo/gotchas").mkdir(parents=True)
    (tmp_path / "repos/demo/gotchas/clock-skew.md").write_text(MANUAL_NOTE, encoding="utf-8")
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    note = await reader.read_note(
        "repos/demo/gotchas/clock-skew.md", area=NoteArea(value="repos/demo")
    )

    assert (note.title, note.kind, note.origin, note.updated) == (
        "Clock skew breaks tokens", "gotcha", "manual", "2026-01-05",
    )  # fmt: skip
    assert note.content == MANUAL_NOTE


@pytest.mark.parametrize(
    "path",
    [
        "repos/other/gotchas/x.md",
        "repos/demo/../../outside.md",
        "/etc/passwd",
        "repos/demo/.hidden/x.md",
        "repos/demo/gotchas/clock-skew.txt",
        "repos/demo/gotchas/missing.md",
    ],
)
async def test_read_note_refuses_anything_outside_the_scope_or_unreadable(
    tmp_path: Path, mapper: NoteMapper, path: str
) -> None:
    (tmp_path / "repos/demo/gotchas").mkdir(parents=True)
    (tmp_path / "repos/demo/gotchas/clock-skew.txt").write_text("x", encoding="utf-8")
    (tmp_path.parent / "outside.md").write_text("secret", encoding="utf-8")
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    with pytest.raises(NoteStorageError):
        await reader.read_note(path, area=NoteArea(value="repos/demo"))


async def test_read_note_refuses_a_symlink_that_leaves_the_vault(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    vault: Path = tmp_path / "vault"
    (vault / "repos/demo").mkdir(parents=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (vault / "repos/demo/link.md").symlink_to(tmp_path / "outside.md")
    reader = FilesystemNoteReadRepositoryAdapter(vault, mapper)

    with pytest.raises(NoteStorageError):
        await reader.read_note("repos/demo/link.md", area=NoteArea(value="repos/demo"))
