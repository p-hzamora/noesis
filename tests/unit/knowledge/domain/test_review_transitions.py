"""accept, reject, retract, supersede on Knowledge and Assertion; revise is closed (FR-004, FR-008,
FR-011; AC-001, AC-008, AC-011)."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import Assertion, Knowledge
from noesis.bounded_context.knowledge.domain.events.knowledge_events import (
    AssertionAccepted,
    AssertionRetracted,
    KnowledgeAccepted,
    KnowledgeRetracted,
    RecordSuperseded,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
    AssertionPredicateEnum,
    GraphContent,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Slug,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    InvalidStatusTransitionError,
    KnowledgeNotRevisableError,
    RevisionConflictError,
)

pytestmark = pytest.mark.unit

ID: RecordId = RecordId(value="0" * 25 + "1")
SPACE: SpaceId = SpaceId(value="0" * 25 + "2")
SOURCE: RecordId = RecordId(value="0" * 25 + "3")
SUBJECT: RecordId = RecordId(value="0" * 25 + "4")
OBJECT: RecordId = RecordId(value="0" * 25 + "5")
CAUSE: RecordId = RecordId(value="0" * 25 + "6")
SUCCESSOR: RecordId = RecordId(value="0" * 25 + "7")
USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
LATER = NOW + timedelta(minutes=5)

PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED
T = ReviewTransitionEnum


def knowledge(status: RecordStatusEnum = PROPOSED) -> Knowledge:
    record = Knowledge.create(
        id=ID,
        space_id=SPACE,
        ownership=OwnershipEnum.GRAPH,
        subtype=Slug(value="decision"),
        applicability=Applicability(),
        actor=AGENT,
        source_ids=(SOURCE,),
        content=GraphContent(title="T", body="B"),
        now=NOW,
    )
    record.collect_events()
    record.status = status
    return record


def assertion(status: RecordStatusEnum = PROPOSED) -> Assertion:
    record = Assertion.propose(
        id=ID,
        space_id=SPACE,
        predicate=AssertionPredicateEnum.SUPPORTS,
        subject_id=SUBJECT,
        object_id=OBJECT,
        subject_at_revision=None,
        object_at_revision=1,
        evidence_ids=(),
        rationale="why",
        actor=AGENT,
        applicability=Applicability(),
        source_ids=(SOURCE,),
        now=NOW,
    )
    record.collect_events()
    record.status = status
    return record


def apply_knowledge(record: Knowledge, transition: ReviewTransitionEnum) -> Any:
    common: dict[str, Any] = {"actor": USER, "now": LATER}
    match transition:
        case T.ACCEPT:
            return record.accept(
                expected_revision=record.head_number,
                reason=None,
                basis=DecisionBasisEnum.USER,
                **common,
            )
        case T.REJECT:
            return record.reject(reason="no", basis=DecisionBasisEnum.USER, **common)
        case T.RETRACT:
            return record.retract(reason="no", basis=DecisionBasisEnum.USER, **common)
        case _:
            return record.supersede(cause=CAUSE, successor=SUCCESSOR, **common)


def apply_assertion(record: Assertion, transition: ReviewTransitionEnum) -> Any:
    common: dict[str, Any] = {"actor": USER, "now": LATER}
    match transition:
        case T.ACCEPT:
            return record.accept(reason=None, basis=DecisionBasisEnum.USER, **common)
        case T.REJECT:
            return record.reject(reason="no", basis=DecisionBasisEnum.USER, **common)
        case T.RETRACT:
            return record.retract(reason="no", basis=DecisionBasisEnum.USER, **common)
        case _:
            return record.supersede(cause=CAUSE, successor=SUCCESSOR, **common)


ALLOWED: dict[tuple[ReviewTransitionEnum, RecordStatusEnum], RecordStatusEnum] = {
    (T.ACCEPT, PROPOSED): ACCEPTED,
    (T.REJECT, PROPOSED): RETRACTED,
    (T.RETRACT, ACCEPTED): RETRACTED,
    (T.SUPERSEDE, ACCEPTED): SUPERSEDED,
}
KINDS: list[tuple[Callable[..., Any], Callable[..., Any]]] = [
    (knowledge, apply_knowledge),
    (assertion, apply_assertion),
]
KIND_IDS: list[str] = ["knowledge", "assertion"]


@pytest.mark.parametrize(("build", "apply"), KINDS, ids=KIND_IDS)
@pytest.mark.parametrize("transition", T)
@pytest.mark.parametrize("current", RecordStatusEnum)
def test_every_transition_and_status_pair_on_both_roots(
    build: Callable[..., Any],
    apply: Callable[..., Any],
    transition: ReviewTransitionEnum,
    current: RecordStatusEnum,
) -> None:
    record = build(current)

    if (transition, current) not in ALLOWED:
        with pytest.raises(InvalidStatusTransitionError):
            apply(record, transition)
        assert record.status is current
        assert record.decision_seq == 0
        assert record.latest_decision is None
        assert record.collect_events() == []
        return

    decision = apply(record, transition)

    assert record.status is ALLOWED[(transition, current)]
    assert record.latest_decision == decision
    assert (decision.seq, decision.transition) == (1, transition)
    assert (decision.from_status, decision.to_status) == (current, record.status)
    assert (decision.actor, decision.decided_at) == (USER, LATER)


@pytest.mark.parametrize(("build", "apply"), KINDS, ids=KIND_IDS)
def test_decision_seq_counts_each_transition_of_the_record(
    build: Callable[..., Any], apply: Callable[..., Any]
) -> None:
    record = build()

    first = apply(record, T.ACCEPT)
    second = apply(record, T.RETRACT)

    assert (first.seq, second.seq) == (1, 2)
    assert record.decision_seq == 2
    assert record.latest_decision == second
    assert (second.from_status, second.to_status) == (ACCEPTED, RETRACTED)


def test_knowledge_accept_pins_the_head_revision_and_nothing_else_does() -> None:
    record = knowledge()
    record.revise(
        expected_revision=1,
        actor=AGENT,
        source_ids=(SOURCE,),
        content=GraphContent(title="T2", body="B2"),
        now=NOW,
    )

    accepted = apply_knowledge(record, T.ACCEPT)
    retracted = apply_knowledge(record, T.RETRACT)

    assert accepted.pinned_revision == 2
    assert retracted.pinned_revision is None
    assert accepted.cause_assertion_id is None


def test_assertion_accept_has_no_pinned_revision() -> None:
    assert apply_assertion(assertion(), T.ACCEPT).pinned_revision is None


def test_knowledge_accept_with_stale_expected_revision_conflicts_and_changes_nothing() -> None:
    record = knowledge()
    record.revise(
        expected_revision=1,
        actor=AGENT,
        source_ids=(SOURCE,),
        content=GraphContent(title="T2", body="B2"),
        now=NOW,
    )
    record.collect_events()

    with pytest.raises(RevisionConflictError) as raised:
        record.accept(
            expected_revision=1,
            actor=AGENT,
            reason=None,
            basis=DecisionBasisEnum.AGENT_PROJECT,
            now=LATER,
        )

    assert raised.value.metadata["expected_revision"] == 1
    assert raised.value.metadata["actual_revision"] == 2
    assert record.status is PROPOSED
    assert record.decision_seq == 0
    assert record.collect_events() == []


def test_knowledge_accept_checks_the_status_before_the_revision() -> None:
    """As C2's revise: an already accepted record is `021` whatever revision the caller names."""
    with pytest.raises(InvalidStatusTransitionError):
        knowledge(ACCEPTED).accept(
            expected_revision=99, actor=USER, reason=None, basis=DecisionBasisEnum.USER, now=LATER
        )


@pytest.mark.parametrize("build", [knowledge, assertion], ids=KIND_IDS)
def test_decision_records_reason_basis_and_cause(build: Callable[..., Any]) -> None:
    record = build()

    rejected = record.reject(
        actor=AGENT, reason="duplicate", basis=DecisionBasisEnum.AGENT_PROJECT, now=LATER
    )

    assert (rejected.reason, rejected.basis) == ("duplicate", DecisionBasisEnum.AGENT_PROJECT)
    assert rejected.actor.session == AGENT.session
    assert (rejected.pinned_revision, rejected.cause_assertion_id) == (None, None)


@pytest.mark.parametrize("build", [knowledge, assertion], ids=KIND_IDS)
def test_supersede_names_its_cause_and_the_effect_basis(build: Callable[..., Any]) -> None:
    record = build(ACCEPTED)

    decision = record.supersede(cause=CAUSE, successor=SUCCESSOR, actor=AGENT, now=LATER)

    assert record.status is SUPERSEDED
    assert record.superseded_by_assertion_id == CAUSE
    assert decision.cause_assertion_id == CAUSE
    assert decision.basis is DecisionBasisEnum.SUPERSESSION_EFFECT
    assert decision.actor == AGENT


@pytest.mark.parametrize(
    ("build", "apply", "transition", "start", "event"),
    [
        (knowledge, apply_knowledge, T.ACCEPT, PROPOSED, KnowledgeAccepted),
        (knowledge, apply_knowledge, T.REJECT, PROPOSED, KnowledgeRetracted),
        (knowledge, apply_knowledge, T.RETRACT, ACCEPTED, KnowledgeRetracted),
        (knowledge, apply_knowledge, T.SUPERSEDE, ACCEPTED, RecordSuperseded),
        (assertion, apply_assertion, T.ACCEPT, PROPOSED, AssertionAccepted),
        (assertion, apply_assertion, T.REJECT, PROPOSED, AssertionRetracted),
        (assertion, apply_assertion, T.RETRACT, ACCEPTED, AssertionRetracted),
        (assertion, apply_assertion, T.SUPERSEDE, ACCEPTED, RecordSuperseded),
    ],
)
def test_each_transition_records_one_event_without_suffix(
    build: Callable[..., Any],
    apply: Callable[..., Any],
    transition: ReviewTransitionEnum,
    start: RecordStatusEnum,
    event: type,
) -> None:
    record = build(start)

    apply(record, transition)

    events = record.collect_events()
    assert len(events) == 1
    assert type(events[0]) is event
    assert not event.__name__.endswith("Event")
    assert (events[0].aggregate_id, events[0].space_id) == (ID.value, SPACE.value)


@pytest.mark.parametrize("status", [ACCEPTED, SUPERSEDED, RETRACTED])
def test_revise_is_closed_once_the_knowledge_left_proposed(status: RecordStatusEnum) -> None:
    """AC-011 (unit): D28, accepted knowledge changes only through a successor record."""
    record = knowledge(status)

    with pytest.raises(KnowledgeNotRevisableError):
        record.revise(
            expected_revision=1,
            actor=AGENT,
            source_ids=(SOURCE,),
            content=GraphContent(title="x", body="y"),
            now=LATER,
        )

    assert record.head_number == 1
