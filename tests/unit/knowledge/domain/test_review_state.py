"""Derived states and the closed vocabularies (FR-009, FR-017; AC-006, AC-020)."""

import pytest

from noesis.bounded_context.knowledge.domain.services.review_state import (
    authority_of,
    effective_status_of,
)
from noesis.bounded_context.knowledge.domain.value_objects import RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    AssertionRoleEnum,
    AuthorityLabelEnum,
    DecisionBasisEnum,
    ReviewRequirementEnum,
    ReviewTransitionEnum,
)

pytestmark = pytest.mark.unit

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED
LABEL = AuthorityLabelEnum


@pytest.mark.parametrize(
    ("stored", "superseded_by_accepted", "effective"),
    [
        (PROPOSED, False, PROPOSED),
        (ACCEPTED, False, ACCEPTED),
        (SUPERSEDED, False, SUPERSEDED),
        (RETRACTED, False, RETRACTED),
        (ACCEPTED, True, SUPERSEDED),
        (SUPERSEDED, True, SUPERSEDED),
        (RETRACTED, True, SUPERSEDED),
        (PROPOSED, True, SUPERSEDED),
        (None, False, None),
        (None, True, None),
    ],
    ids=[
        "proposed",
        "accepted",
        "superseded",
        "retracted",
        "accepted-effect-pending",
        "superseded-again",
        "retracted-before-the-effect",
        "proposed-targeted",
        "no-status",
        "no-status-targeted",
    ],
)
def test_effective_status_is_superseded_whenever_an_accepted_supersedes_targets_the_record(
    stored: RecordStatusEnum | None,
    superseded_by_accepted: bool,
    effective: RecordStatusEnum | None,
) -> None:
    assert effective_status_of(stored, superseded_by_accepted=superseded_by_accepted) is effective


@pytest.mark.parametrize(
    ("effective", "label"),
    [
        (None, LABEL.NOT_REVIEWABLE),
        (RETRACTED, LABEL.RETRACTED),
        (SUPERSEDED, LABEL.SUPERSEDED),
        (PROPOSED, LABEL.PROPOSED),
        (ACCEPTED, LABEL.AUTHORITATIVE),
    ],
)
def test_authority_label_for_each_effective_status(
    effective: RecordStatusEnum | None, label: AuthorityLabelEnum
) -> None:
    assert authority_of(effective) is label


def test_effective_status_then_authority_for_an_accepted_record_with_a_pending_effect() -> None:
    effective = effective_status_of(ACCEPTED, superseded_by_accepted=True)

    assert authority_of(effective) is LABEL.SUPERSEDED


def test_authority_label_has_exactly_the_five_published_members() -> None:
    assert {member.value for member in AuthorityLabelEnum} == {
        "authoritative",
        "proposed",
        "superseded",
        "retracted",
        "not_reviewable",
    }
    assert len(AuthorityLabelEnum) == 5


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (DecisionBasisEnum, {"user", "agent_project", "supersession_effect", "migration"}),
        (ReviewTransitionEnum, {"accept", "reject", "retract", "supersede"}),
        (ReviewRequirementEnum, {"user", "agent_or_user"}),
        (AssertionRoleEnum, {"subject", "object", "evidence", "any"}),
    ],
)
def test_review_vocabularies_are_closed_sets(enum: type, values: set[str]) -> None:
    assert {member.value for member in enum} == values  # type: ignore[attr-defined]
