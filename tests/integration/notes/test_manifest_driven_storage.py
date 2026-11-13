"""Location-independent reads, multi-source dedup, update in place and the collision suffix."""

from datetime import date
from pathlib import Path

import pytest
from tests.support.notes_support import FixedClock, a_decision, a_draft

from noesis.bounded_context.notes.application.handlers.commands import (
    ApplyCurationCommand,
    ApplyCurationHandler,
)
from noesis.bounded_context.notes.application.services.manifest import (
    SourceRoleEnum,
    SourceSpec,
    SourceTypeEnum,
)
from noesis.bounded_context.notes.domain.policies import AutoCurationPolicy
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    NoteFrontmatter,
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
)
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.ids import UlidNoteIdGeneratorAdapter
from noesis.bounded_context.notes.infrastructure.outbound.manifest import (
    YamlManifestProviderAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FilesystemNoteReadRepositoryAdapter,
    FilesystemNoteRepositoryAdapter,
    FilesystemNotesUnitOfWorkAdapter,
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper

pytestmark = pytest.mark.integration

CODEC = YamlFrontmatterCodecAdapter()
MAPPER = NoteMapper(CODEC)
ID_A: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
ID_B: str = "01ARZ3NDEKTSV4RRFFQ69G5FAW"


def _note_text(note_id: str, scope: str, kind: str, title: str, body: str) -> str:
    frontmatter = NoteFrontmatter(
        id=NoteId(value=note_id),
        scope=NoteScope.parse(scope),
        kind=NoteKind(value=kind),
        origin=NoteOriginEnum.MANUAL,
        updated=date(2026, 11, 1),
    )
    return CODEC.render(frontmatter, f"\n# {title}\n\n## Decision\n\n{body}\n")


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


async def test_a_note_in_an_arbitrary_folder_is_found_by_frontmatter(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "my/own/shelf/whatever.md",
        _note_text(ID_A, "repo:demo", "decision", "Cache", "ttl cache"),
    )
    _write(tmp_path, "my/own/readme.md", "# Plain\n\nttl cache but no noesis block\n")
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, MAPPER)

    found = await reader.search("cache", scope=None, limit=5)
    assert [n.path for n in found.notes] == ["my/own/shelf/whatever.md"]
    assert (found.notes[0].id, found.notes[0].scope, found.notes[0].kind) == (
        ID_A,
        "repo:demo",
        "decision",
    )

    by_id = await reader.find_by_id(NoteId(value=ID_A), scope=None)
    assert by_id is not None and by_id.path == "my/own/shelf/whatever.md"
    assert await reader.find_by_id(NoteId(value=ID_B), scope=None) is None

    active = await reader.find_active(NoteScope.parse("repo:demo"), NoteKind(value="decision"))
    assert [n.id for n in active] == [ID_A]
    assert await reader.find_active(NoteScope.parse("repo:other"), NoteKind(value="decision")) == []
    assert [
        n.id for n in await reader.list_notes(scope=NoteScope.parse("repo:demo"), origin=None)
    ] == [ID_A]
    assert (await reader.read_note("my/own/shelf/whatever.md", scope=None)).id == ID_A


async def test_multi_source_recall_dedups_by_id_and_primary_wins(tmp_path: Path) -> None:
    primary_dir, other_dir = tmp_path / "primary", tmp_path / "other"
    _write(
        primary_dir,
        "p/shared.md",
        _note_text(ID_A, "repo:demo", "decision", "Shared cache", "cache"),
    )
    _write(
        other_dir,
        "o/shared-copy.md",
        _note_text(ID_A, "repo:demo", "decision", "Shared cache", "cache"),
    )
    _write(other_dir, "o/only.md", _note_text(ID_B, "repo:demo", "decision", "Only cache", "cache"))

    def source(name: str, role: SourceRoleEnum) -> SourceSpec:
        return SourceSpec(name=name, type=SourceTypeEnum.FILESYSTEM, path=name, role=role)

    multi = MultiSourceNoteReadRepositoryAdapter(
        [
            SourceReader(source("other", SourceRoleEnum.READ), FilesystemNoteReadRepositoryAdapter(other_dir, MAPPER)),
            SourceReader(source("primary", SourceRoleEnum.PRIMARY), FilesystemNoteReadRepositoryAdapter(primary_dir, MAPPER)),
        ]
    )  # fmt: skip
    found = await multi.search("cache", scope=None, limit=10)
    assert sorted(n.id for n in found.notes) == [ID_A, ID_B]
    assert {n.id: n.path for n in found.notes}[ID_A] == "p/shared.md"
    listed = await multi.list_notes(scope=None, origin=None)
    assert sorted(n.id for n in listed) == [ID_A, ID_B]
    assert (await multi.find_by_id(NoteId(value=ID_B), scope=None)) is not None  # type: ignore[truthy-bool]


def _apply_handler(vault: Path) -> ApplyCurationHandler:
    clock = FixedClock()
    return ApplyCurationHandler(
        uow_factory=lambda: FilesystemNotesUnitOfWorkAdapter(
            FilesystemNoteRepositoryAdapter(vault, MAPPER)
        ),
        clock=clock,
        policy=AutoCurationPolicy(),
        manifest=YamlManifestProviderAdapter(vault),
        ids=UlidNoteIdGeneratorAdapter(clock),
        read_repository=FilesystemNoteReadRepositoryAdapter(vault, MAPPER),
    )


def _command(*decisions: object) -> ApplyCurationCommand:
    return ApplyCurationCommand(scope=NoteScope.parse("repo:demo"), decisions=tuple(decisions))  # type: ignore[arg-type]


async def test_create_writes_no_auto_folder_then_update_keeps_the_id(tmp_path: Path) -> None:
    handler = _apply_handler(tmp_path)
    created = await handler.handle(_command(a_decision()))
    assert created.created == ("repos/demo/decisions/use-ttl-cache.md",)
    path = tmp_path / created.created[0]
    first = CODEC.parse(path.read_text(encoding="utf-8")).frontmatter
    assert first is not None and first.origin is NoteOriginEnum.AUTO
    assert not (tmp_path / "repos/demo/auto").exists()

    revised = a_decision(CurationActionEnum.UPDATE, a_draft(title="Use a TTL cache v2"))
    updated = await handler.handle(_command(revised))
    assert updated.updated == created.created and updated.created == ()
    second = CODEC.parse(path.read_text(encoding="utf-8")).frontmatter
    assert second is not None and second.id == first.id  # in place, same identity
    assert "v2" in path.read_text(encoding="utf-8")
    assert sorted(p.name for p in path.parent.iterdir()) == ["use-ttl-cache.md"]


async def test_a_taken_path_gets_a_numeric_suffix_and_is_never_overwritten(tmp_path: Path) -> None:
    taken = tmp_path / "repos/demo/decisions/use-ttl-cache.md"
    taken.parent.mkdir(parents=True)
    taken.write_text("# my own plain note, no noesis block\n", encoding="utf-8")
    handler = _apply_handler(tmp_path)

    first = await handler.handle(_command(a_decision()))
    assert first.created == ("repos/demo/decisions/use-ttl-cache-2.md",)
    assert taken.read_text(encoding="utf-8") == "# my own plain note, no noesis block\n"

    other_kind = a_decision(draft=a_draft(slug="use-ttl-cache", title="Other"))
    other_scope = ApplyCurationCommand(scope=NoteScope.parse("topic:rust"), decisions=(other_kind,))
    topic = await handler.handle(other_scope)
    assert topic.created == ("learning/rust/decisions/use-ttl-cache.md",)
