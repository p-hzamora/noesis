"""Recall must resolve the selected record, even when sources reuse filenames."""

from pathlib import Path

import pytest
from tests.support.notes_support import (
    DefaultManifestProvider,
    FixedClock,
    ScriptedRecallAgent,
    note_file,
    path_note_id,
)

from noesis.bounded_context.notes.application.dtos import BriefingItemDto, RecallBriefingDto
from noesis.bounded_context.notes.application.handlers.queries import (
    RecallNotesHandler,
    RecallNotesQuery,
)
from noesis.bounded_context.notes.application.services.manifest import (
    SourceRoleEnum,
    SourceSpec,
    SourceTypeEnum,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FilesystemNoteReadRepositoryAdapter,
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from noesis.interfaces.cli.bootstrap.notes_handlers_builder import build_note_mapper

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("synthesize", [False, True])
async def test_distinct_records_at_the_same_relative_path_survive_recall(
    tmp_path: Path, synthesize: bool
) -> None:
    readers: list[SourceReader] = []
    identities: list[str] = []
    for name, role in (("primary", SourceRoleEnum.PRIMARY), ("other", SourceRoleEnum.READ)):
        root: Path = tmp_path / name
        root.mkdir()
        identity: str = path_note_id(name).value
        identities.append(identity)
        content: str = note_file(
            "decision.md", title=f"Cache {name}", scope="repo:demo", body=f"Evidence from {name}."
        ).replace(path_note_id("decision.md").value, identity)
        (root / "decision.md").write_text(content, encoding="utf-8")
        readers.append(
            SourceReader(
                SourceSpec(name=name, type=SourceTypeEnum.FILESYSTEM, path=str(root), role=role),
                FilesystemNoteReadRepositoryAdapter(root, build_note_mapper()),
            )
        )
    agent = ScriptedRecallAgent(
        RecallBriefingDto(
            summary="Two distinct decisions.",
            decisions=(
                BriefingItemDto(text="Primary evidence", sources=(identities[0],)),
                BriefingItemDto(text="Other evidence", sources=(identities[1],)),
                BriefingItemDto(text="Ambiguous evidence", sources=("decision.md",)),
            ),
        )
    )
    handler = RecallNotesHandler(
        read_repository=MultiSourceNoteReadRepositoryAdapter(readers),
        manifest=DefaultManifestProvider(),
        clock=FixedClock(),
        agent=agent,
    )

    result = await handler.handle(RecallNotesQuery(task="cache", synthesize=synthesize))

    assert result.considered == 2
    assert {entry.id for entry in result.entries} == set(identities)
    if synthesize:
        assert {note.id: note.content.splitlines()[-1] for note in agent.calls[0][1]} == {
            identities[0]: "Evidence from primary.",
            identities[1]: "Evidence from other.",
        }
        assert result.briefing is not None
        assert [item.source_ids for item in result.briefing.decisions] == [
            (identities[0],),
            (identities[1],),
        ]
        assert [item.text for item in result.briefing.unsupported] == ["Ambiguous evidence"]
    else:
        assert not agent.calls


async def test_id_read_follows_a_rename_and_rejects_replacement_or_wrong_scope(
    tmp_path: Path,
) -> None:
    from noesis.bounded_context.notes.domain.value_objects import NoteId, NoteScope
    from noesis.exceptions import NoteStorageError

    original: Path = tmp_path / "original.md"
    original.write_text(
        note_file("original.md", title="Cache", scope="repo:demo"), encoding="utf-8"
    )
    identity: NoteId = path_note_id("original.md")
    reader = FilesystemNoteReadRepositoryAdapter(tmp_path, build_note_mapper())
    original.rename(tmp_path / "renamed.md")
    original.write_text(
        note_file("replacement.md", title="Other", scope="repo:other"), encoding="utf-8"
    )

    resolved = await reader.read_by_id(identity, scope=None, path_hint="original.md")

    assert resolved.id == identity.value
    assert resolved.path == "renamed.md"
    with pytest.raises(NoteStorageError):
        await reader.read_by_id(
            identity, scope=NoteScope.parse("repo:other"), path_hint="renamed.md"
        )
    (tmp_path / "renamed.md").unlink()
    with pytest.raises(NoteStorageError, match="does not match"):
        await reader.read_by_id(identity, scope=None, path_hint="original.md")
    with pytest.raises(NoteStorageError, match="No note found"):
        await reader.read_by_id(identity, scope=None)


async def test_repeated_identity_at_different_paths_is_one_recall_candidate() -> None:
    from tests.support.notes_support import InMemoryNoteReadRepository, a_summary

    original = a_summary("original.md")
    alias = original.model_copy(update={"path": "alias.md"})
    handler = RecallNotesHandler(
        read_repository=InMemoryNoteReadRepository([original, alias]),
        manifest=DefaultManifestProvider(),
        clock=FixedClock(),
    )

    result = await handler.handle(RecallNotesQuery(task="cache", synthesize=False))

    assert result.considered == 1
    assert len(result.entries) == 1
    assert result.entries[0].id == original.id
