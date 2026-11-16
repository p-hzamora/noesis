"""Eligibility, dismissed-pair and progress policies of a consolidation."""

import pytest

from noesis.bounded_context.knowledge.domain.services import (
    ConsolidationEligibilityPolicy,
    ConsolidationProgressPolicy,
    DismissedPairPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    MIGRATED_TAG,
    ConsolidationProgressEnum,
    DismissedPair,
    MemberCandidate,
    RecordId,
    RecordStatusEnum,
    Slug,
)
from noesis.exceptions import IneligibleConsolidationMemberError, InvalidConsolidationError

pytestmark = pytest.mark.unit

ACCEPTED = RecordStatusEnum.ACCEPTED
DECISION = Slug(value="decision")
GOTCHA = Slug(value="gotcha")
PROJECT_A = RecordId(value=f"{900:026d}")
PROJECT_B = RecordId(value=f"{901:026d}")


def rid(number: int) -> RecordId:
    return RecordId(value=f"{number:026d}")


def cand(number: int, **overrides: object) -> MemberCandidate:
    values: dict[str, object] = {
        "record_id": rid(number),
        "effective_status": ACCEPTED,
        "subtype": DECISION,
        "project_id": PROJECT_A,
        "head_revision": 1,
    }
    values.update(overrides)
    return MemberCandidate(**values)


def cause_of(*candidates: MemberCandidate) -> IneligibleConsolidationMemberError:
    with pytest.raises(IneligibleConsolidationMemberError) as raised:
        ConsolidationEligibilityPolicy.check(candidates)
    return raised.value


def test_check_pins_members_at_head_revision_in_id_order() -> None:
    members = ConsolidationEligibilityPolicy.check(
        [cand(3, head_revision=4), cand(1, head_revision=2), cand(2, head_revision=None)]
    )

    assert [(m.record_id.value, m.at_revision) for m in members] == [
        (rid(1).value, 2),
        (rid(2).value, 1),  # unknown head defaults to revision 1
        (rid(3).value, 4),
    ]


def test_check_accepts_space_wide_members() -> None:
    members = ConsolidationEligibilityPolicy.check(
        [cand(1, project_id=None), cand(2, project_id=None)]
    )

    assert len(members) == 2


@pytest.mark.parametrize(
    ("overrides", "cause"),
    [
        ({"effective_status": RecordStatusEnum.PROPOSED}, "not_accepted"),
        ({"effective_status": RecordStatusEnum.RETRACTED}, "retracted"),
        ({"effective_status": RecordStatusEnum.SUPERSEDED}, "superseded"),
        ({"effective_status": None}, "unknown"),
        ({"is_knowledge": False}, "not_knowledge"),
        ({"found": False}, "not_found"),
    ],
)
def test_check_names_member_and_cause(overrides: dict[str, object], cause: str) -> None:
    error = cause_of(cand(1), cand(2, **overrides))

    assert error.metadata == {"member_id": rid(2).value, "cause": cause}


def test_check_not_found_takes_precedence_over_other_flags() -> None:
    error = cause_of(cand(1), cand(2, found=False, is_knowledge=False))

    assert error.metadata["cause"] == "not_found"


def test_check_reports_subtype_mismatch_on_later_member() -> None:
    error = cause_of(cand(1), cand(2, subtype=GOTCHA))

    assert error.metadata == {"member_id": rid(2).value, "cause": "subtype_mismatch"}


@pytest.mark.parametrize("other_project", [PROJECT_B, None])
def test_check_reports_project_mismatch(other_project: RecordId | None) -> None:
    error = cause_of(cand(1), cand(2, project_id=other_project))

    assert error.metadata == {"member_id": rid(2).value, "cause": "project_mismatch"}


@pytest.mark.parametrize("count", [0, 1, 11])
def test_check_rejects_member_count_out_of_range(count: int) -> None:
    with pytest.raises(InvalidConsolidationError):
        ConsolidationEligibilityPolicy.check([cand(n) for n in range(1, count + 1)])


def test_check_rejects_duplicates() -> None:
    with pytest.raises(InvalidConsolidationError, match="more than once"):
        ConsolidationEligibilityPolicy.check([cand(1), cand(2), cand(1)])


def test_check_ids_accepts_bounds_and_rejects_outside() -> None:
    ConsolidationEligibilityPolicy.check_ids(["a", "b"])
    ConsolidationEligibilityPolicy.check_ids([str(n) for n in range(10)])
    with pytest.raises(InvalidConsolidationError):
        ConsolidationEligibilityPolicy.check_ids(["a"])
    with pytest.raises(InvalidConsolidationError):
        ConsolidationEligibilityPolicy.check_ids([str(n) for n in range(11)])
    with pytest.raises(InvalidConsolidationError, match="more than once"):
        ConsolidationEligibilityPolicy.check_ids(["a", "a"])


def test_proposed_migrated_member_points_to_user_review_step() -> None:
    error = cause_of(
        cand(1),
        cand(2, effective_status=RecordStatusEnum.PROPOSED, tags=(MIGRATED_TAG,)),
    )

    assert error.metadata["cause"] == "not_accepted"
    assert len(error.next_steps) == 1
    assert "noesis review accept --tag origin:migrated --all --yes" in error.next_steps[0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"effective_status": RecordStatusEnum.PROPOSED},  # proposed but not migrated
        {"effective_status": RecordStatusEnum.RETRACTED, "tags": (MIGRATED_TAG,)},
    ],
)
def test_other_ineligible_members_get_generic_next_step(overrides: dict[str, object]) -> None:
    error = cause_of(cand(1), cand(2, **overrides))

    assert "migrated" not in error.next_steps[0].lower()


def pair(first: int, first_revision: int, second: int, second_revision: int) -> DismissedPair:
    return DismissedPair(
        consolidation_id="C",
        first_id=rid(first).value,
        first_revision=first_revision,
        second_id=rid(second).value,
        second_revision=second_revision,
    )


@pytest.mark.parametrize(
    ("revisions", "suppressed"),
    [
        ({rid(1).value: 1, rid(2).value: 2}, True),
        ({rid(1).value: 2, rid(2).value: 2}, False),
        ({rid(1).value: 1, rid(2).value: 3}, False),
        ({rid(1).value: 1}, False),
        ({}, False),
    ],
)
def test_dismissed_pair_suppresses_only_at_judged_revisions(
    revisions: dict[str, int], suppressed: bool
) -> None:
    judged = pair(1, 1, 2, 2)

    result = DismissedPairPolicy.suppressing([judged], revisions)

    assert result == ([judged] if suppressed else [])


def test_dismissed_pair_keeps_only_still_valid_pairs() -> None:
    valid, stale = pair(1, 1, 2, 1), pair(3, 1, 4, 1)

    result = DismissedPairPolicy.suppressing(
        [valid, stale], {rid(1).value: 1, rid(2).value: 1, rid(3).value: 2, rid(4).value: 1}
    )

    assert result == [valid]


@pytest.mark.parametrize(
    ("materialised", "successor", "assertions", "members", "expected"),
    [
        (False, None, [], [], "pending"),
        (False, "retracted", ["accepted"], ["superseded"], "pending"),
        (True, "retracted", ["accepted"], ["accepted"], "successor_retracted"),
        (True, "accepted", ["accepted", "accepted"], ["superseded", "superseded"], "applied"),
        (True, "proposed", ["proposed", "proposed"], ["accepted", "accepted"], "pending"),
        (True, "proposed", [None, "proposed"], ["accepted", "accepted"], "pending"),
        (True, "accepted", ["proposed", "proposed"], ["accepted", "accepted"], "partially_applied"),
        (
            True,
            "proposed",
            ["accepted", "proposed"],
            ["superseded", "accepted"],
            "partially_applied",
        ),
        (
            True,
            "accepted",
            ["accepted", "accepted"],
            ["superseded", "accepted"],
            "partially_applied",
        ),
    ],
)
def test_progress_derivation(
    materialised: bool,
    successor: str | None,
    assertions: list[str | None],
    members: list[str | None],
    expected: str,
) -> None:
    progress = ConsolidationProgressPolicy.derive(
        materialised=materialised,
        successor_status=successor,
        assertion_statuses=assertions,
        member_statuses=members,
    )

    assert progress is ConsolidationProgressEnum(expected)
