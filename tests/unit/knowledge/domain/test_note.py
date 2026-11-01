"""The Note aggregate."""

from datetime import timedelta

import pytest
from tests.support.knowledge_support import NOW, a_draft, a_note

from noesis.bounded_context.knowledge.domain.entities import Note, NoteCreated, NoteRevised
from noesis.bounded_context.knowledge.domain.value_objects import (
    NoteArea,
    NoteKindEnum,
    NoteOriginEnum,
    NoteSection,
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
        area=NoteArea.for_repository("demo"),
        origin=NoteOriginEnum.AUTO,
        draft=draft,
        commits=("abc", "abc", "def"),
        session="abcd1234",
        now=NOW,
    )

    assert [s.heading for s in note.sections] == [*NoteKindEnum.DECISION.required_sections, "notes"]
    assert note.sections[0].body == "Not recorded"
    assert note.sections[1].body == "single instance"
    assert note.commits == ("abc", "def")
    assert note.id == "auto-decision-use-ttl-cache"
    assert note.tags == ("decision", "demo", "auto")
    assert [type(event) for event in note.collect_events()] == [NoteCreated]


def test_manual_notes_have_plain_ids_and_no_auto_tag() -> None:
    note: Note = a_note(origin=NoteOriginEnum.MANUAL)

    assert note.id == "decision-use-ttl-cache"
    assert "auto" not in note.tags


def test_auto_notes_can_be_revised_merging_commits() -> None:
    note: Note = a_note()
    later = NOW + timedelta(days=1)

    note.revise(
        a_draft(title="Use a TTL cache, revisited"), commits=("new",), session="ffff0000", now=later
    )

    assert note.title == "Use a TTL cache, revisited"
    assert note.commits == ("new",)
    assert note.updated_at == later
    assert note.session == "ffff0000"
    assert isinstance(note.collect_events()[-1], NoteRevised)


def test_manual_notes_cannot_be_revised_by_automation() -> None:
    with pytest.raises(ManualNoteProtectedError):
        a_note(origin=NoteOriginEnum.MANUAL).revise(a_draft(), commits=(), session=None, now=NOW)
