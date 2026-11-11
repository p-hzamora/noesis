"""Filesystem note storage: mapper, repository, unit of work and read repository."""

from pathlib import Path

import pytest
from tests.support.notes_support import a_note, a_scope

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import (
    NoteKind,
    NoteOriginEnum,
    NotePath,
    NoteScope,
)
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
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
noesis:
  id: 01ARZ3NDEKTSV4RRFFQ69G5FAW
  scope: repo:demo
  kind: gotcha
  origin: manual
  sources: []
  updated: 2026-01-05
---

# Clock skew breaks tokens

## Symptom

Tokens rejected right after login.
"""
MANUAL_PATH: str = "repos/demo/gotchas/clock-skew.md"


@pytest.fixture
def mapper() -> NoteMapper:
    return NoteMapper(YamlFrontmatterCodecAdapter())


def _write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")


async def test_committed_notes_are_written_as_markdown_and_read_back(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    note: Note = a_note()
    unit = FilesystemNotesUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(tmp_path, mapper))

    async with unit as uow:
        await uow.notes.save(note)
        await uow.commit()

    text: str = (tmp_path / note.path.value).read_text(encoding="utf-8")
    assert text.startswith("---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n  scope: repo:demo\n")
    assert "origin: auto" in text
    assert "updated: 2026-10-30" in text
    assert "# Use a TTL cache\n\n## Decision\n\nKeep tokens in memory." in text
    loaded: Note | None = await FilesystemNoteRepositoryAdapter(tmp_path, mapper).get(note.path)
    assert loaded is not None
    assert (loaded.id, loaded.title, loaded.sources) == (note.id, note.title, note.sources)
    assert loaded.sections == note.sections
    assert loaded.updated_at.date() == note.updated_at.date()


async def test_leaving_without_commit_writes_nothing(tmp_path: Path, mapper: NoteMapper) -> None:
    async with FilesystemNotesUnitOfWorkAdapter(
        FilesystemNoteRepositoryAdapter(tmp_path, mapper)
    ) as uow:
        await uow.notes.save(a_note())
        assert await uow.notes.get(a_note().path) is not None  # staged notes are visible
        assert await uow.notes.exists(a_note().path)

    assert not any(tmp_path.rglob("*.md"))


async def test_a_hand_written_noesis_note_loads_and_a_plain_file_is_not_a_note(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    _write(tmp_path, MANUAL_PATH, MANUAL_NOTE)
    _write(tmp_path, "plain.md", "# Just a document\n")
    repository = FilesystemNoteRepositoryAdapter(tmp_path, mapper)

    note = await repository.get(NotePath(value=MANUAL_PATH))
    plain = await repository.get(NotePath(value="plain.md"))

    assert note is not None
    assert note.origin is NoteOriginEnum.MANUAL
    assert [section.heading for section in note.sections] == ["Symptom"]
    assert plain is None
    assert await repository.exists(NotePath(value="plain.md"))
    assert not await repository.exists(NotePath(value="absent.md"))


async def test_read_repository_lists_filters_and_ranks_notes(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    _write(tmp_path, MANUAL_PATH, MANUAL_NOTE)
    _write(tmp_path, "repos/demo/index.md", "# index")
    _write(tmp_path, ".obsidian/decisions/x.md", "# hidden")
    unit = FilesystemNotesUnitOfWorkAdapter(FilesystemNoteRepositoryAdapter(tmp_path, mapper))
    async with unit as uow:
        await uow.notes.save(a_note())
        await uow.commit()
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    everything = await reader.list_notes(scope=None, origin=None)
    auto_only = await reader.list_notes(scope=a_scope(), origin=NoteOriginEnum.AUTO)
    found = (await reader.search("token clock", scope=None, limit=5)).notes
    nothing = (await reader.search("a an", scope=None, limit=5)).notes
    elsewhere = await reader.list_notes(scope=NoteScope.for_repository("other"), origin=None)
    active = await reader.find_active(a_scope(), NoteKind(value="gotcha"))

    assert [note.path for note in everything] == [
        "repos/demo/decisions/use-ttl-cache.md",
        MANUAL_PATH,
    ]
    assert [note.origin for note in auto_only] == ["auto"]
    assert found[0].path == MANUAL_PATH
    assert found[0].snippet == "Tokens rejected right after login."
    assert (nothing, elsewhere) == ((), [])
    assert [note.path for note in active] == [MANUAL_PATH]


def test_frontmatter_errors_are_tolerated(mapper: NoteMapper) -> None:
    parsed = mapper.parse("---\n: [unclosed\n---\n# Title\n\n## Cause\n\nx\n")

    assert parsed.frontmatter is None
    assert parsed.title == "Title"


async def test_read_note_returns_the_whole_file_inside_the_scope(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    _write(tmp_path, MANUAL_PATH, MANUAL_NOTE)
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    note = await reader.read_note(MANUAL_PATH, scope=a_scope())

    assert (note.id, note.title, note.kind, note.origin, note.updated) == (
        "01ARZ3NDEKTSV4RRFFQ69G5FAW", "Clock skew breaks tokens", "gotcha", "manual", "2026-01-05",
    )  # fmt: skip
    assert note.content == MANUAL_NOTE


@pytest.mark.parametrize(
    "path",
    [
        "repos/demo/../../outside.md",
        "/etc/passwd",
        "repos/demo/.hidden/x.md",
        "repos/demo/gotchas/clock-skew.txt",
        "repos/demo/gotchas/missing.md",
        "plain.md",
    ],
)
async def test_read_note_refuses_anything_outside_the_vault_or_not_a_note(
    tmp_path: Path, mapper: NoteMapper, path: str
) -> None:
    _write(tmp_path, "repos/demo/gotchas/clock-skew.txt", "x")
    _write(tmp_path, "plain.md", "# plain")
    (tmp_path.parent / "outside.md").write_text("secret", encoding="utf-8")
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    with pytest.raises(NoteStorageError):
        await reader.read_note(path, scope=None)


async def test_read_note_refuses_another_scope(tmp_path: Path, mapper: NoteMapper) -> None:
    _write(tmp_path, MANUAL_PATH, MANUAL_NOTE)
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, mapper)

    with pytest.raises(NoteStorageError):
        await reader.read_note(MANUAL_PATH, scope=NoteScope.for_repository("other"))


async def test_read_note_refuses_a_symlink_that_leaves_the_vault(
    tmp_path: Path, mapper: NoteMapper
) -> None:
    vault: Path = tmp_path / "vault"
    (vault / "repos/demo").mkdir(parents=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (vault / "repos/demo/link.md").symlink_to(tmp_path / "outside.md")
    reader = FilesystemNoteReadRepositoryAdapter(vault, mapper)

    with pytest.raises(NoteStorageError):
        await reader.read_note("repos/demo/link.md", scope=a_scope())


async def test_updating_a_note_keeps_the_keys_the_user_added(tmp_path: Path) -> None:
    note: Note = a_note()
    file = tmp_path / note.path.value
    file.parent.mkdir(parents=True)
    mapper = NoteMapper(YamlFrontmatterCodecAdapter())
    stored: str = mapper.to_markdown(note)
    file.write_text(
        stored.replace(
            "---\nnoesis:", "---\ntags: [infra]\naliases: [ttl]\ncreated: 2026-01-02\nnoesis:", 1
        ),
        encoding="utf-8",
    )

    repository = FilesystemNoteRepositoryAdapter(tmp_path, mapper)
    await repository.save(note)
    repository.flush()

    header = mapper._codec.parse(file.read_text(encoding="utf-8")).header
    assert header["tags"] == ["infra"] and header["aliases"] == ["ttl"]
    assert header["created"] == "2026-01-02"
    assert list(header)[-1] == "noesis"
