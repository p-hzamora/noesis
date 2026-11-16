"""Curation value objects: the work brief's submission key, candidates, the plan hash."""

import hashlib
import json

import pytest
from tests.support.curation_support import SECRET_GH, SHA1, SHA2, experience, knowledge, skip

from noesis.bounded_context.knowledge.application.services.curation_redactor import (
    CurationRedactor,
)
from noesis.bounded_context.knowledge.domain.services import CurationAdmissionPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    DEFAULT_CURATION_SUBTYPES,
    CandidateKindEnum,
    CommitRef,
    CurationCandidate,
    CurationPlan,
    PlanEntry,
    ProposeKnowledge,
    RecordExperience,
    Skip,
    WorkBrief,
)

pytestmark = pytest.mark.unit


def a_brief(**overrides: object) -> WorkBrief:
    fields: dict[str, object] = {
        "session_id": "sess-1",
        "repository": "acme",
        "head": SHA2,
        "commits": (CommitRef(sha=SHA1, subject="add parser"), CommitRef(sha=SHA2, subject="fix")),
        "goal": "Harden the parser",
        "excerpt": "We fixed the offset bug.",
        **overrides,
    }
    return WorkBrief.model_validate(fields)


def test_submission_key_is_the_sha256_of_the_canonical_json_of_the_five_fields() -> None:
    brief = a_brief()

    canonical = json.dumps(
        {
            "contract_version": 1,
            "session_id": "sess-1",
            "repository": "acme",
            "head": SHA2,
            "commits": [SHA1, SHA2],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert brief.submission_key() == hashlib.sha256(canonical.encode()).hexdigest()


def test_the_excerpt_goal_and_subjects_do_not_change_the_submission_key() -> None:
    assert a_brief(excerpt="another").submission_key() == a_brief().submission_key()
    assert a_brief(goal="other goal").submission_key() == a_brief().submission_key()


@pytest.mark.parametrize(
    "changed",
    [
        {
            "commits": (
                CommitRef(sha=SHA2, subject="fix"),
                CommitRef(sha=SHA1, subject="add parser"),
            )
        },
        {"head": SHA1},
        {"session_id": "sess-2"},
        {"repository": "other"},
    ],
    ids=["swapped commit order", "another head", "another session", "another repository"],
)
def test_the_commit_order_head_session_and_repository_change_the_submission_key(
    changed: dict[str, object],
) -> None:
    assert a_brief(**changed).submission_key() != a_brief().submission_key()


def test_search_text_is_the_goal_and_the_commit_subjects() -> None:
    assert a_brief().search_text() == "Harden the parser add parser fix"


def test_the_commit_shas_keep_their_order() -> None:
    assert a_brief().commit_shas() == (SHA1, SHA2)


def plan_of(*candidates: CurationCandidate) -> CurationPlan:
    return CurationAdmissionPolicy().plan(candidates, project_key="acme", targets={})


def test_plan_hash_is_stable_whatever_the_order_the_json_keys_were_built_in() -> None:
    plan = plan_of(experience(), knowledge())

    reloaded = CurationPlan.model_validate(json.loads(plan.model_dump_json()))
    shuffled = CurationPlan.model_validate(
        json.loads(json.dumps(plan.model_dump(mode="json"), sort_keys=True))
    )

    assert plan.plan_hash() == reloaded.plan_hash() == shuffled.plan_hash()
    assert len(plan.plan_hash()) == 64


def test_another_plan_has_another_hash() -> None:
    assert plan_of(experience()).plan_hash() != plan_of(experience(body="other")).plan_hash()


def test_a_plan_holding_a_secret_hashes_as_its_redacted_form() -> None:
    leaky = knowledge(body=f"token {SECRET_GH} leaked")
    clean = knowledge(body="token [REDACTED] leaked")

    plan = plan_of(CurationRedactor.candidate(leaky))

    assert plan.plan_hash() == plan_of(clean).plan_hash()
    assert SECRET_GH not in plan.model_dump_json()


def test_ordinals_start_at_one_and_a_skipped_candidate_keeps_its_position() -> None:
    plan = plan_of(skip("s1"), experience("e1"), knowledge("k1"))

    assert [entry.ordinal for entry in plan.entries] == [1, 2, 3]
    assert isinstance(plan.entries[0].write, Skip)
    assert plan.entry(2) is not None
    assert plan.entry(9) is None


def test_a_plan_round_trips_through_json_with_its_planned_writes() -> None:
    plan = CurationPlan(
        entries=(
            PlanEntry(ordinal=1, candidate=experience(), write=RecordExperience()),
            PlanEntry(
                ordinal=2,
                candidate=knowledge(),
                write=ProposeKnowledge(target_record_id="T", reason="x", evidence_ordinals=(1,)),
            ),
        )
    )

    assert CurationPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    ("candidate", "flaw"),
    [
        (CurationCandidate(), "missing kind"),
        (
            CurationCandidate(kind=CandidateKindEnum.EXPERIENCE, subtype="x", body="b"),
            "missing key",
        ),
        (
            CurationCandidate(kind=CandidateKindEnum.EXPERIENCE, key="e", body="b"),
            "missing subtype",
        ),
        (
            CurationCandidate(kind=CandidateKindEnum.EXPERIENCE, key="e", subtype="x"),
            "missing body",
        ),
        (knowledge(title=None), "knowledge needs a title"),
        (knowledge(target="T"), "a target or evidence needs a reason"),
        (knowledge(evidence=("e1",)), "a target or evidence needs a reason"),
        (
            CurationCandidate(
                kind=CandidateKindEnum.EXPERIENCE,
                key="e",
                subtype="observation",
                body="b",
                evidence_keys=("x",),
                reason="r",
            ),
            "only knowledge may name a target or evidence",
        ),
        (CurationCandidate(kind=CandidateKindEnum.SKIP, key="s"), "a skip needs a reason"),
        (CurationCandidate(flaw="title is not text"), "title is not text"),
    ],
)
def test_an_entry_names_its_own_flaw(candidate: CurationCandidate, flaw: str) -> None:
    assert candidate.entry_flaw() == flaw


def test_a_complete_entry_has_no_flaw() -> None:
    assert experience().entry_flaw() is None
    assert knowledge().entry_flaw() is None
    assert knowledge(target="T", reason="refines T").entry_flaw() is None
    assert skip().entry_flaw() is None


def test_the_default_subtypes_are_the_q003_sets() -> None:
    assert DEFAULT_CURATION_SUBTYPES.knowledge == {
        "concept",
        "convention",
        "howto",
        "decision",
        "glossary",
    }
    assert DEFAULT_CURATION_SUBTYPES.experience == {"observation", "outcome", "failure"}
