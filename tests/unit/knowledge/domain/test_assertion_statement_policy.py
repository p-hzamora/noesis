"""AssertionStatementPolicy: the kind matrix, evidence kinds, project rule, space (FR-002; AC-009)."""

import itertools

import pytest

from noesis.bounded_context.knowledge.domain.services.assertion_statement_policy import (
    AssertionStatementPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
    SpaceId,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_reference import RecordReference
from noesis.exceptions import InvalidAssertionError

pytestmark = pytest.mark.unit

SPACE: SpaceId = SpaceId(value="0" * 25 + "1")
OTHER_SPACE: SpaceId = SpaceId(value="0" * 25 + "2")
ACME: RecordId = RecordId(value="0" * 25 + "7")
OTHER: RecordId = RecordId(value="0" * 25 + "8")

K, E, A = RecordTypeEnum.KNOWLEDGE, RecordTypeEnum.EXPERIENCE, RecordTypeEnum.ASSERTION
S, P, C = RecordTypeEnum.SOURCE, RecordTypeEnum.PROJECT, RecordTypeEnum.CATALOG_ENTRY
SUPPORTS, CONTRADICTS = AssertionPredicateEnum.SUPPORTS, AssertionPredicateEnum.CONTRADICTS
SUPERSEDES, RECOMMENDS = AssertionPredicateEnum.SUPERSEDES, AssertionPredicateEnum.RECOMMENDS

# the kind matrix of 20-review.md, as (predicate, subject kind, object kind)
VALID_KINDS: set[tuple[AssertionPredicateEnum, RecordTypeEnum, RecordTypeEnum]] = {
    (SUPPORTS, K, K),
    (SUPPORTS, E, K),
    (CONTRADICTS, K, K),
    (CONTRADICTS, E, K),
    (SUPERSEDES, K, K),
    (SUPERSEDES, A, A),
    (RECOMMENDS, K, K),
    (RECOMMENDS, E, K),
    (RECOMMENDS, K, C),
    (RECOMMENDS, E, C),
}
SUBJECT_KINDS: dict[AssertionPredicateEnum, set[RecordTypeEnum]] = {
    predicate: {s for p, s, _ in VALID_KINDS if p == predicate}
    for predicate in AssertionPredicateEnum
}
ALL_KINDS: tuple[RecordTypeEnum, ...] = (K, E, A, S, P, C)
HAS_STATUS: set[RecordTypeEnum] = {K, A}
_counter = itertools.count(10)


def ref(
    kind: RecordTypeEnum,
    *,
    project: RecordId | None = None,
    space: SpaceId = SPACE,
    status: RecordStatusEnum | None = None,
) -> RecordReference:
    return RecordReference(
        record_id=RecordId(value=f"{next(_counter):026d}"),
        record_type=kind,
        space_id=space,
        project_id=project,
        effective_status=status or (RecordStatusEnum.ACCEPTED if kind in HAS_STATUS else None),
        head_revision=1 if kind in (K, C) else None,
    )


def check(
    predicate: AssertionPredicateEnum,
    subject: RecordReference,
    object_: RecordReference,
    *,
    evidence: tuple[RecordReference, ...] = (),
    project: RecordId | None = None,
    space: SpaceId = SPACE,
) -> None:
    AssertionStatementPolicy.check(
        space_id=space,
        predicate=predicate,
        project_id=project,
        subject=subject,
        object=object_,
        evidence=evidence,
    )


@pytest.mark.parametrize(
    ("predicate", "subject_kind", "object_kind"),
    list(itertools.product(AssertionPredicateEnum, ALL_KINDS, ALL_KINDS)),
)
def test_kind_matrix_accepts_exactly_the_tabled_combinations(
    predicate: AssertionPredicateEnum, subject_kind: RecordTypeEnum, object_kind: RecordTypeEnum
) -> None:
    """Pass for the table; otherwise KNOWLEDGE_020 names `subject` when the subject kind is
    not allowed for the predicate at all, else `object`."""
    subject, object_ = ref(subject_kind), ref(object_kind)

    if (predicate, subject_kind, object_kind) in VALID_KINDS:
        check(predicate, subject, object_)
        return
    with pytest.raises(InvalidAssertionError) as raised:
        check(predicate, subject, object_)
    expected = "subject" if subject_kind not in SUBJECT_KINDS[predicate] else "object"
    assert raised.value.metadata["field"] == expected


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_evidence_kinds_are_experience_knowledge_and_source(kind: RecordTypeEnum) -> None:
    subject, object_ = ref(E), ref(K)

    if kind in (E, K, S):
        check(SUPPORTS, subject, object_, evidence=(ref(kind),))
        return
    with pytest.raises(InvalidAssertionError) as raised:
        check(SUPPORTS, subject, object_, evidence=(ref(E), ref(kind)))
    assert raised.value.metadata["field"] == "evidence"


@pytest.mark.parametrize(
    ("assertion_project", "object_project", "ok"),
    [
        (None, None, True),
        (ACME, ACME, True),
        (ACME, None, False),
        (None, ACME, False),
        (ACME, OTHER, False),
    ],
    ids=["both-space-wide", "same-project", "project-vs-global", "global-vs-project", "differ"],
)
def test_supersedes_needs_the_same_project_on_assertion_and_object(
    assertion_project: RecordId | None, object_project: RecordId | None, ok: bool
) -> None:
    subject, object_ = ref(K, project=assertion_project), ref(K, project=object_project)

    if ok:
        check(SUPERSEDES, subject, object_, project=assertion_project)
        return
    with pytest.raises(InvalidAssertionError) as raised:
        check(SUPERSEDES, subject, object_, project=assertion_project)
    assert raised.value.metadata["field"] == "project"


def test_project_rule_applies_to_supersedes_only() -> None:
    """`E supports K` proposed under another project is a different, valid statement (AC-010)."""
    check(SUPPORTS, ref(E), ref(K, project=None), project=OTHER)
    check(RECOMMENDS, ref(K), ref(C), project=ACME)


@pytest.mark.parametrize("wrong", ["subject", "object", "evidence"])
def test_reference_from_another_space_is_invalid_and_named(wrong: str) -> None:
    other = OTHER_SPACE
    subject = ref(E, space=other if wrong == "subject" else SPACE)
    object_ = ref(K, space=other if wrong == "object" else SPACE)
    evidence = (ref(E, space=other if wrong == "evidence" else SPACE),)

    with pytest.raises(InvalidAssertionError) as raised:
        check(SUPPORTS, subject, object_, evidence=evidence)

    assert raised.value.metadata["field"] == wrong


def test_proposing_ignores_the_status_of_endpoints() -> None:
    """A `supersedes` with a proposed subject and a retracted object still passes the policy."""
    subject = ref(K, status=RecordStatusEnum.PROPOSED)
    object_ = ref(K, status=RecordStatusEnum.RETRACTED)

    check(SUPERSEDES, subject, object_)
