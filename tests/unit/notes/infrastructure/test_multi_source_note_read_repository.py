"""The multi-source reader fuses its sources, primary first, and honours scope on lookups."""

import pytest
from tests.support.notes_support import InMemoryNoteReadRepository, a_summary

from noesis.bounded_context.notes.application.services.manifest import (
    SourceRoleEnum,
    SourceSpec,
    SourceTypeEnum,
)
from noesis.bounded_context.notes.domain.value_objects import NoteId, NoteScope
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from noesis.exceptions import NoteStorageError

pytestmark = pytest.mark.unit

PRIMARY = SourceSpec(
    name="vault", type=SourceTypeEnum.FILESYSTEM, path=".", role=SourceRoleEnum.PRIMARY
)
INDEX = SourceSpec(name="notes", type=SourceTypeEnum.VECTOR, path=".", role=SourceRoleEnum.INDEX)


async def test_a_second_source_ranking_is_fused_after_the_primary() -> None:
    cached = a_summary("repos/demo/decisions/a.md", title="Cache")
    other = a_summary("repos/demo/decisions/b.md", title="Other")
    primary = InMemoryNoteReadRepository([cached, other], match_all=False)
    semantic = InMemoryNoteReadRepository([other])
    multi = MultiSourceNoteReadRepositoryAdapter(
        [SourceReader(INDEX, semantic), SourceReader(PRIMARY, primary)]
    )

    found = await multi.search("cache", scope=None, limit=5)

    assert [note.id for note in found.notes] == [cached.id, other.id]


async def test_find_by_id_skips_a_note_of_another_scope() -> None:
    note = a_summary("repos/demo/decisions/a.md", scope="repo:demo")
    multi = MultiSourceNoteReadRepositoryAdapter(
        [SourceReader(PRIMARY, InMemoryNoteReadRepository([note]))]
    )

    assert await multi.find_by_id(NoteId(value=note.id), scope=None) is not None
    assert await multi.find_by_id(NoteId(value=note.id), scope=NoteScope.parse("repo:x")) is None


async def test_read_note_tries_the_next_source_and_reports_the_first_failure() -> None:
    note = a_summary("repos/demo/decisions/a.md")
    broken = InMemoryNoteReadRepository([note], unreadable=[note.path])
    healthy = InMemoryNoteReadRepository([note])
    other = SourceSpec(name="b", type=SourceTypeEnum.FILESYSTEM, path="b", role=SourceRoleEnum.READ)

    both = MultiSourceNoteReadRepositoryAdapter(
        [SourceReader(PRIMARY, broken), SourceReader(other, healthy)]
    )
    only_broken = MultiSourceNoteReadRepositoryAdapter([SourceReader(PRIMARY, broken)])

    assert (await both.read_note(note.path, scope=None)).id == note.id
    with pytest.raises(NoteStorageError):
        await only_broken.read_note(note.path, scope=None)
