"""The vector stub answers nothing; an index plugged into the multi-source adapter is fused."""

import pytest
from tests.support.notes_support import InMemoryNoteReadRepository, a_summary

from noesis.bounded_context.notes.application.dtos import VectorHitDto
from noesis.bounded_context.notes.application.ports.vector import IVectorSearch
from noesis.bounded_context.notes.application.services.manifest import (
    SourceRoleEnum,
    SourceSpec,
    SourceTypeEnum,
)
from noesis.bounded_context.notes.domain.value_objects import NoteId
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    MultiSourceNoteReadRepositoryAdapter,
    SourceReader,
)
from noesis.bounded_context.notes.infrastructure.outbound.vector import StubVectorSearchAdapter
from noesis.exceptions import NoteStorageError

pytestmark = pytest.mark.unit

SPEC = SourceSpec(
    name="vault", type=SourceTypeEnum.FILESYSTEM, path=".", role=SourceRoleEnum.PRIMARY
)


class _Index(IVectorSearch):
    def __init__(self, *hits: VectorHitDto) -> None:
        self._hits: tuple[VectorHitDto, ...] = hits

    async def search(self, query: str, k: int) -> tuple[VectorHitDto, ...]:
        return self._hits[:k]


async def test_the_stub_finds_nothing() -> None:
    assert await StubVectorSearchAdapter().search("anything", 5) == ()


async def test_an_index_hit_is_resolved_to_a_note_and_fused_with_the_text_search() -> None:
    cached = a_summary("repos/demo/decisions/a.md", title="Cache")
    other = a_summary("repos/demo/decisions/b.md", title="Other")
    repository = InMemoryNoteReadRepository([cached, other], match_all=False)
    index = _Index(VectorHitDto(id=other.id, path=other.path, rank=0))
    multi = MultiSourceNoteReadRepositoryAdapter([SourceReader(SPEC, repository)], index=index)

    found = await multi.search("cache", scope=None, limit=5)

    assert [note.id for note in found.notes] == [cached.id, other.id]


async def test_read_note_tries_the_next_source_and_reports_the_first_failure() -> None:
    note = a_summary("repos/demo/decisions/a.md")
    broken = InMemoryNoteReadRepository([note], unreadable=[note.path])
    healthy = InMemoryNoteReadRepository([note])
    other = SourceSpec(name="b", type=SourceTypeEnum.FILESYSTEM, path="b", role=SourceRoleEnum.READ)

    both = MultiSourceNoteReadRepositoryAdapter(
        [SourceReader(SPEC, broken), SourceReader(other, healthy)]
    )
    only_broken = MultiSourceNoteReadRepositoryAdapter([SourceReader(SPEC, broken)])

    assert (await both.read_note(note.path, scope=None)).id == note.id
    with pytest.raises(NoteStorageError):
        await only_broken.read_note(note.path, scope=None)
    assert await both.find_by_id(NoteId(value=note.id)) is not None
