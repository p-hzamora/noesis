"""Rules that turn curator decisions into stored notes or reported skips."""

import pytest
from tests.support.knowledge_support import NOW, a_decision, a_note

from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.policies import (
    AutoCurationPolicy,
    CurationOutcome,
    CurationOutcomeEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteArea,
    NoteOriginEnum,
)

pytestmark = pytest.mark.unit

AREA = NoteArea.for_repository("demo")


def _apply(
    decision: CurationDecision, *, auto: Note | None = None, manual: Note | None = None
) -> CurationOutcome:
    return AutoCurationPolicy().apply(
        decision,
        area=AREA,
        existing_auto=auto,
        existing_manual=manual,
        commits=("abc",),
        session="abcd1234",
        now=NOW,
    )


def test_new_knowledge_becomes_an_auto_note() -> None:
    outcome: CurationOutcome = _apply(a_decision())

    assert outcome.outcome is CurationOutcomeEnum.CREATED
    assert outcome.note is not None
    assert outcome.note.location.relative_path == "repos/demo/auto/decisions/use-ttl-cache.md"


@pytest.mark.parametrize("action", [CurationActionEnum.CREATE, CurationActionEnum.UPDATE])
def test_existing_auto_notes_are_revised_whatever_verb_the_curator_used(
    action: CurationActionEnum,
) -> None:
    existing: Note = a_note()

    outcome: CurationOutcome = _apply(a_decision(action=action), auto=existing)

    assert outcome.outcome is CurationOutcomeEnum.UPDATED
    assert outcome.note is existing


def test_a_manual_note_on_the_same_topic_wins() -> None:
    manual: Note = a_note(origin=NoteOriginEnum.MANUAL)

    outcome: CurationOutcome = _apply(a_decision(), manual=manual)

    assert outcome.outcome is CurationOutcomeEnum.SKIPPED
    assert outcome.reason == "covered by repos/demo/decisions/use-ttl-cache.md"
    assert outcome.note is None


def test_skips_keep_the_curator_reason_and_drafts_are_required() -> None:
    skipped: CurationOutcome = _apply(a_decision(action=CurationActionEnum.SKIP))
    malformed: CurationOutcome = _apply(
        CurationDecision(action=CurationActionEnum.CREATE, candidate="x", reason="r", draft=None)
    )

    assert (skipped.outcome, skipped.reason) == (
        CurationOutcomeEnum.SKIPPED,
        "single instance, no shared state",
    )
    assert malformed.reason == "malformed decision: no note draft"
