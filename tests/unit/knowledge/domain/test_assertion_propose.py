"""Assertion.propose: creation invariants and the judged revisions (FR-001, FR-002; AC-009)."""

from datetime import timedelta
from typing import Any

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import Assertion
from noesis.bounded_context.knowledge.domain.events import AssertionProposed
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.exceptions import InvalidAssertionError

pytestmark = pytest.mark.unit

ID: RecordId = RecordId(value="0" * 25 + "1")
SPACE: SpaceId = SpaceId(value="0" * 25 + "2")
SUBJECT: RecordId = RecordId(value="0" * 25 + "3")
OBJECT: RecordId = RecordId(value="0" * 25 + "4")
EVIDENCE: RecordId = RecordId(value="0" * 25 + "5")
SOURCE: RecordId = RecordId(value="0" * 25 + "6")


def propose(**overrides: Any) -> Assertion:
    values: dict[str, Any] = {
        "id": ID,
        "space_id": SPACE,
        "predicate": AssertionPredicateEnum.SUPPORTS,
        "subject_id": SUBJECT,
        "object_id": OBJECT,
        "subject_at_revision": None,
        "object_at_revision": 1,
        "evidence_ids": (EVIDENCE,),
        "rationale": "The experience shows it.",
        "actor": AGENT,
        "applicability": Applicability(),
        "source_ids": (SOURCE,),
        "now": NOW,
    }
    return Assertion.propose(**{**values, **overrides})


def test_propose_creates_proposed_assertion_with_event_and_judged_revisions() -> None:
    assertion = propose(subject_at_revision=3, object_at_revision=2, now=NOW + timedelta(hours=1))

    assert assertion.status is RecordStatusEnum.PROPOSED
    assert (assertion.subject_at_revision, assertion.object_at_revision) == (3, 2)
    assert assertion.created_at == NOW + timedelta(hours=1)
    assert assertion.decision_seq == 0
    assert assertion.latest_decision is None
    assert assertion.superseded_by_assertion_id is None
    events = assertion.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], AssertionProposed)
    assert events[0].aggregate_id == ID.value


def test_propose_keeps_none_revision_for_types_without_revisions() -> None:
    assertion = propose(subject_at_revision=None, object_at_revision=None)

    assert assertion.subject_at_revision is None
    assert assertion.object_at_revision is None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"object_id": SUBJECT}, "object"),
        ({"rationale": ""}, "rationale"),
        ({"rationale": "   \n"}, "rationale"),
        ({"source_ids": ()}, "sources"),
        ({"evidence_ids": (EVIDENCE, OBJECT)}, "evidence"),
    ],
    ids=[
        "subject-equals-object",
        "empty-rationale",
        "blank-rationale",
        "no-source",
        "evidence-contains-object",
    ],
)
def test_propose_rejects_broken_invariant_naming_the_field(
    overrides: dict[str, Any], field: str
) -> None:
    with pytest.raises(InvalidAssertionError) as raised:
        propose(**overrides)

    assert raised.value.metadata["field"] == field
    assert raised.value.error_code == "KNOWLEDGE_020_INVALID_ASSERTION"


def test_propose_rejects_nothing_about_the_status_of_endpoints_it_cannot_see() -> None:
    """A `supersedes` can be proposed with any subject: only ids and revisions reach `propose`."""
    assertion = propose(
        predicate=AssertionPredicateEnum.SUPERSEDES, evidence_ids=(), object_at_revision=1
    )

    assert assertion.status is RecordStatusEnum.PROPOSED
