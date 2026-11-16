"""The Consolidation aggregate and its value objects (spec 20-consolidation)."""

import hashlib
from datetime import timedelta

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import Consolidation
from noesis.bounded_context.knowledge.domain.entities.consolidation import fingerprint_of
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    ConsolidationId,
    ConsolidationMember,
    ConsolidationStateEnum,
    DismissalReasonKindEnum,
    RecordId,
    SpaceId,
)
from noesis.exceptions import (
    ConsolidationClosedError,
    ConsolidationNotMaterialisedError,
    InvalidConsolidationError,
    InvalidRecordIdError,
)

pytestmark = pytest.mark.unit

SPACE: SpaceId = SpaceId(value=f"{99:026d}")
USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
LATER = NOW + timedelta(minutes=5)


def rid(number: int) -> RecordId:
    return RecordId(value=f"{number:026d}")


def member(number: int, revision: int = 1) -> ConsolidationMember:
    return ConsolidationMember(record_id=rid(number), at_revision=revision)


def make(
    members: tuple[ConsolidationMember, ...] | None = None, rationale: str = "they overlap"
) -> Consolidation:
    return Consolidation.create(
        id=ConsolidationId(value=f"{500:026d}"),
        space_id=SPACE,
        members=members if members is not None else (member(1), member(2)),
        rationale=rationale,
        project_id=None,
        actor=AGENT,
        now=NOW,
    )


def materialised(count: int = 2) -> Consolidation:
    consolidation = make(tuple(member(n) for n in range(1, count + 1)))
    consolidation.materialise(
        successor_id=rid(100), assertion_ids=tuple(rid(200 + n) for n in range(count)), now=NOW
    )
    return consolidation


def dismiss(consolidation: Consolidation) -> bool:
    return consolidation.dismiss(
        reason_kind=DismissalReasonKindEnum.DISTINCT, reason="different", actor=USER, now=LATER
    )


def test_consolidation_id_accepts_ulid() -> None:
    assert ConsolidationId(value=f"{1:026d}").value == f"{1:026d}"


@pytest.mark.parametrize("value", ["", "abc", "0" * 25, "0" * 27, "I" * 26, "8" + "0" * 25])
def test_consolidation_id_rejects_non_ulid(value: str) -> None:
    with pytest.raises(InvalidRecordIdError):
        ConsolidationId(value=value)


@pytest.mark.parametrize("count", [2, 3, 10])
def test_create_accepts_two_to_ten_members(count: int) -> None:
    consolidation = make(tuple(member(n) for n in range(1, count + 1)))

    assert len(consolidation.members) == count
    assert consolidation.state is ConsolidationStateEnum.OPENED
    assert consolidation.version == 1
    assert consolidation.created_by == AGENT
    assert consolidation.successor_id is None
    assert consolidation.produced_assertion_ids == ()
    assert consolidation.dismissal is None


@pytest.mark.parametrize("count", [0, 1, 11])
def test_create_rejects_wrong_member_count(count: int) -> None:
    with pytest.raises(InvalidConsolidationError) as raised:
        make(tuple(member(n) for n in range(1, count + 1)))

    assert raised.value.metadata == {"member_count": count}


def test_create_rejects_duplicate_member() -> None:
    with pytest.raises(InvalidConsolidationError, match="more than once"):
        make((member(1), member(2), member(1, revision=4)))


@pytest.mark.parametrize("rationale", ["", "   ", "\n\t"])
def test_create_rejects_blank_rationale(rationale: str) -> None:
    with pytest.raises(InvalidConsolidationError, match="rationale"):
        make(rationale=rationale)


def test_create_sorts_members_by_record_id() -> None:
    consolidation = make((member(3), member(1), member(2)))

    assert [m.record_id.value for m in consolidation.members] == [
        rid(1).value,
        rid(2).value,
        rid(3).value,
    ]


def test_create_fingerprint_is_order_independent_and_revision_sensitive() -> None:
    first = make((member(2), member(1)))
    second = make((member(1), member(2)))
    other_revision = make((member(1), member(2, revision=2)))

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != other_revision.fingerprint


def test_fingerprint_hashes_sorted_pairs() -> None:
    pairs = f"{rid(1).value}:1,{rid(2).value}:3"
    expected = f"sha256:{hashlib.sha256(pairs.encode()).hexdigest()}"

    assert fingerprint_of((member(1, 1), member(2, 3))) == expected


def test_materialise_moves_to_materialised_and_records_proposals() -> None:
    consolidation = make()

    changed = consolidation.materialise(
        successor_id=rid(100), assertion_ids=(rid(201), rid(202)), now=LATER
    )

    assert changed is True
    assert consolidation.state is ConsolidationStateEnum.MATERIALISED
    assert consolidation.successor_id == rid(100)
    assert consolidation.produced_assertion_ids == (rid(201), rid(202))
    assert consolidation.version == 2
    assert consolidation.updated_at == LATER


def test_materialise_requires_one_assertion_per_member() -> None:
    consolidation = make((member(1), member(2), member(3)))

    with pytest.raises(InvalidConsolidationError) as raised:
        consolidation.materialise(successor_id=rid(100), assertion_ids=(rid(201),), now=LATER)

    assert raised.value.metadata == {"members": 3, "assertions": 1}
    assert consolidation.state is ConsolidationStateEnum.OPENED
    assert consolidation.version == 1


def test_materialise_replay_is_noop() -> None:
    consolidation = materialised()

    changed = consolidation.materialise(
        successor_id=rid(999), assertion_ids=(rid(998), rid(997)), now=LATER
    )

    assert changed is False
    assert consolidation.successor_id == rid(100)
    assert consolidation.version == 2


def test_materialise_after_acceptance_started_is_noop() -> None:
    consolidation = materialised()
    consolidation.start_acceptance(now=LATER)

    assert consolidation.materialise(successor_id=rid(1), assertion_ids=(), now=LATER) is False
    assert consolidation.version == 3


def test_materialise_dismissed_raises_closed() -> None:
    consolidation = make()
    dismiss(consolidation)

    with pytest.raises(ConsolidationClosedError) as raised:
        consolidation.materialise(
            successor_id=rid(100), assertion_ids=(rid(201), rid(202)), now=LATER
        )

    assert raised.value.metadata["state"] == "dismissed"


def test_start_acceptance_from_materialised() -> None:
    consolidation = materialised()

    assert consolidation.start_acceptance(now=LATER) is True
    assert consolidation.state is ConsolidationStateEnum.ACCEPTANCE_STARTED
    assert consolidation.version == 3
    assert consolidation.updated_at == LATER


def test_start_acceptance_replay_is_noop() -> None:
    consolidation = materialised()
    consolidation.start_acceptance(now=LATER)

    assert consolidation.start_acceptance(now=LATER + timedelta(hours=1)) is False
    assert consolidation.version == 3
    assert consolidation.updated_at == LATER


def test_start_acceptance_on_opened_raises_not_materialised() -> None:
    consolidation = make()

    with pytest.raises(ConsolidationNotMaterialisedError) as raised:
        consolidation.start_acceptance(now=LATER)

    assert raised.value.metadata == {"consolidation_id": consolidation.id.value}
    assert consolidation.state is ConsolidationStateEnum.OPENED
    assert consolidation.version == 1


def test_start_acceptance_on_dismissed_raises_closed() -> None:
    consolidation = materialised()
    dismiss(consolidation)

    with pytest.raises(ConsolidationClosedError):
        consolidation.start_acceptance(now=LATER)


@pytest.mark.parametrize("materialise_first", [False, True])
def test_dismiss_from_opened_or_materialised(materialise_first: bool) -> None:
    consolidation = materialised() if materialise_first else make()
    before = consolidation.version

    assert dismiss(consolidation) is True

    assert consolidation.state is ConsolidationStateEnum.DISMISSED
    assert consolidation.version == before + 1
    assert consolidation.dismissal is not None
    assert consolidation.dismissal.reason_kind is DismissalReasonKindEnum.DISTINCT
    assert consolidation.dismissal.reason == "different"
    assert consolidation.dismissal.actor == USER
    assert consolidation.dismissal.dismissed_at == LATER


def test_dismiss_replay_is_noop_and_keeps_first_dismissal() -> None:
    consolidation = make()
    dismiss(consolidation)

    changed = consolidation.dismiss(
        reason_kind=DismissalReasonKindEnum.OTHER, reason="again", actor=AGENT, now=LATER
    )

    assert changed is False
    assert consolidation.version == 2
    assert consolidation.dismissal is not None
    assert consolidation.dismissal.reason == "different"


def test_dismiss_after_acceptance_started_raises_closed() -> None:
    consolidation = materialised()
    consolidation.start_acceptance(now=LATER)

    with pytest.raises(ConsolidationClosedError) as raised:
        dismiss(consolidation)

    assert raised.value.metadata["state"] == "acceptance_started"
    assert consolidation.dismissal is None


@pytest.mark.parametrize(
    ("steps", "holds"),
    [
        ((), True),
        (("materialise",), True),
        (("materialise", "accept"), True),
        (("dismiss",), False),
        (("materialise", "dismiss"), False),
    ],
)
def test_holds_membership_until_dismissed(steps: tuple[str, ...], holds: bool) -> None:
    consolidation = make()
    for step in steps:
        if step == "materialise":
            consolidation.materialise(
                successor_id=rid(100), assertion_ids=(rid(201), rid(202)), now=LATER
            )
        elif step == "accept":
            consolidation.start_acceptance(now=LATER)
        else:
            dismiss(consolidation)

    assert consolidation.holds_membership is holds
