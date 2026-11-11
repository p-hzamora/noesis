"""Rules that turn curator decisions into stored notes or reported skips."""

import pytest
from tests.support.notes_support import NOW, a_decision, a_note, a_scope

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.policies import (
    AutoCurationPolicy,
    CurationOutcome,
    CurationOutcomeEnum,
)
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteId,
    NoteOriginEnum,
    NotePath,
    NotePlacement,
    NoteSourceRef,
)

pytestmark = pytest.mark.unit

PLACEMENT = NotePlacement(
    id=NoteId(value="01ARZ3NDEKTSV4RRFFQ69G5FAB"),
    path=NotePath(value="repos/demo/decisions/use-ttl-cache.md"),
    required_sections=("Decision", "Rationale"),
)


def _apply(
    decision: CurationDecision,
    *,
    auto: Note | None = None,
    manual_path: NotePath | None = None,
    placement: NotePlacement | None = PLACEMENT,
) -> CurationOutcome:
    return AutoCurationPolicy().apply(
        decision,
        scope=a_scope(),
        existing_auto=auto,
        manual_path=manual_path,
        placement=placement,
        sources=(NoteSourceRef(value="commit:abc"),),
        now=NOW,
    )


def test_new_notes_becomes_an_auto_note_at_the_placed_path() -> None:
    outcome: CurationOutcome = _apply(a_decision())

    assert outcome.outcome is CurationOutcomeEnum.CREATED
    assert outcome.note is not None
    assert outcome.note.path == PLACEMENT.path
    assert outcome.note.id == PLACEMENT.id
    assert outcome.note.origin is NoteOriginEnum.AUTO


@pytest.mark.parametrize("action", [CurationActionEnum.CREATE, CurationActionEnum.UPDATE])
def test_existing_auto_notes_are_revised_in_place_whatever_verb_the_curator_used(
    action: CurationActionEnum,
) -> None:
    existing: Note = a_note()
    identity: NoteId = existing.id

    outcome: CurationOutcome = _apply(a_decision(action=action), auto=existing)

    assert outcome.outcome is CurationOutcomeEnum.UPDATED
    assert outcome.note is existing
    assert existing.id == identity


def test_a_manual_note_on_the_same_topic_wins() -> None:
    path = NotePath(value="repos/demo/decisions/use-ttl-cache.md")

    outcome: CurationOutcome = _apply(a_decision(), manual_path=path)

    assert outcome.outcome is CurationOutcomeEnum.SKIPPED
    assert outcome.reason == "covered by repos/demo/decisions/use-ttl-cache.md"
    assert outcome.note is None


def test_skips_keep_the_curator_reason_and_drafts_are_required() -> None:
    skipped: CurationOutcome = _apply(a_decision(action=CurationActionEnum.SKIP), placement=None)
    malformed: CurationOutcome = _apply(
        CurationDecision(action=CurationActionEnum.CREATE, candidate="x", reason="r", draft=None),
        placement=None,
    )

    assert (skipped.outcome, skipped.reason) == (
        CurationOutcomeEnum.SKIPPED,
        "single instance, no shared state",
    )
    assert malformed.reason == "malformed decision: no note draft"
