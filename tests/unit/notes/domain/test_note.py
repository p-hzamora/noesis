"""The Note aggregate."""

from datetime import timedelta

import pytest
from tests.support.notes_support import NOW, a_draft, a_note

from noesis.bounded_context.notes.domain.entities import Note, NoteCreated, NoteRevised
from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteOriginEnum,
    NotePath,
    NoteScope,
    NoteSection,
    NoteSourceRef,
)
from noesis.exceptions import (
    ManualNoteProtectedError,
)

pytestmark = pytest.mark.unit


def test_creation_completes_required_sections_in_order_and_keeps_extras_last() -> None:
    draft = a_draft().model_copy(
        update={
            "sections": (
                NoteSection(heading="notes", body="extra"),
                NoteSection(heading="rationale", body="single instance"),
            )
        }
    )

    note = Note.create(
        id=NoteId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV"),
        scope=NoteScope.for_repository("demo"),
        origin=NoteOriginEnum.AUTO,
        path=NotePath(value="anywhere/use-ttl-cache.md"),
        draft=draft,
        required_sections=("Decision", "Rationale"),
        sources=(NoteSourceRef(value="commit:abc"), NoteSourceRef(value="commit:abc")),
        now=NOW,
    )

    assert [s.heading for s in note.sections] == ["Decision", "Rationale", "notes"]
    assert note.sections[0].body == "Not recorded"
    assert note.sections[1].body == "single instance"
    assert [s.value for s in note.sources] == ["commit:abc"]
    assert note.frontmatter.id == note.id
    assert [type(event) for event in note.collect_events()] == [NoteCreated]


def test_auto_notes_can_be_revised_merging_sources_and_keeping_the_id() -> None:
    note: Note = a_note()
    later = NOW + timedelta(days=1)
    identity = note.id

    note.revise(
        a_draft(title="Use a TTL cache, revisited"),
        required_sections=("Decision",),
        sources=(NoteSourceRef(value="commit:new"),),
        now=later,
    )

    assert note.id == identity
    assert note.title == "Use a TTL cache, revisited"
    assert [s.value for s in note.sources] == ["commit:new"]
    assert note.updated_at == later
    assert isinstance(note.collect_events()[-1], NoteRevised)


def test_manual_notes_cannot_be_revised_by_automation() -> None:
    with pytest.raises(ManualNoteProtectedError):
        a_note(origin=NoteOriginEnum.MANUAL).revise(
            a_draft(), required_sections=(), sources=(), now=NOW
        )
