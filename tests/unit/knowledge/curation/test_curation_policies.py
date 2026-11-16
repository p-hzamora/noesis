"""The admission table (rows 1-12), the capture keys and the progress transitions."""

import pytest
from tests.support.curation_support import experience, knowledge, skip

from noesis.bounded_context.knowledge.domain.services import (
    CaptureKeyPolicy,
    CurationAdmissionPolicy,
    CurationProgressPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    MIGRATED_TAG,
    CandidateKindEnum,
    CurationCandidate,
    CurationFailureReasonEnum,
    CurationStageEnum,
    CurationTarget,
    PlannedWrite,
    ProposeKnowledge,
    ProposeSuccessor,
    RecordExperience,
    ReviseProposal,
    Skip,
)
from noesis.exceptions import InvalidCurationTransitionError

pytestmark = pytest.mark.unit

PROJECT = "acme"
TARGET_ID = "01HZZZZZZZZZZZZZZZZZZZZZZ1"


def target(
    *,
    status: str | None = "proposed",
    project: str | None = PROJECT,
    record_type: str = "knowledge",
    tags: tuple[str, ...] = (),
    revision: int | None = 3,
) -> CurationTarget:
    return CurationTarget(
        record_id=TARGET_ID,
        record_type=record_type,
        status=status,
        project_key=project,
        head_revision=revision,
        tags=tags,
    )


def decide(
    candidate: CurationCandidate,
    found: CurationTarget | None = None,
    *,
    assertions: bool = True,
) -> PlannedWrite:
    return CurationAdmissionPolicy(assertions_available=assertions).decide(
        candidate, project_key=PROJECT, target=found
    )


def refining(**overrides: object) -> CurationCandidate:
    return knowledge(target=TARGET_ID, reason="refines the target", **overrides)  # type: ignore[arg-type]


# ----- rows 1 to 5 -----


def test_row_1_a_curator_skip_is_skipped_with_its_reason() -> None:
    assert decide(skip(reason="in the README")) == Skip(reason="curator: in the README")


def test_row_2_a_malformed_entry_is_skipped_with_the_detail() -> None:
    assert decide(knowledge(title=None)) == Skip(reason="malformed: knowledge needs a title")


def test_row_2_a_flaw_found_across_the_plan_wins_over_a_valid_entry() -> None:
    write = CurationAdmissionPolicy().decide(
        experience(), project_key=PROJECT, target=None, flaw="key 'e1' is used twice"
    )

    assert write == Skip(reason="malformed: key 'e1' is used twice")


def test_row_3_an_unknown_subtype_is_skipped() -> None:
    assert decide(experience(subtype="rumour")) == Skip(reason="unknown_subtype")
    assert decide(knowledge(subtype="observation")) == Skip(reason="unknown_subtype")
    assert decide(experience(subtype="decision")) == Skip(reason="unknown_subtype")


@pytest.mark.parametrize("subtype", ["observation", "outcome", "failure"])
def test_row_4_an_experience_is_recorded(subtype: str) -> None:
    assert decide(experience(subtype=subtype)) == RecordExperience()


@pytest.mark.parametrize("subtype", ["concept", "convention", "howto", "decision", "glossary"])
def test_row_5_knowledge_without_a_target_is_proposed(subtype: str) -> None:
    assert decide(knowledge(subtype=subtype)) == ProposeKnowledge()


# ----- rows 6 to 12, parametrised over target shapes, with and without the migrated tag -----

STATUSES = ["proposed", "accepted", "superseded", "retracted"]


@pytest.mark.parametrize("tags", [(), (MIGRATED_TAG,), ("area:parser", MIGRATED_TAG)])
def test_row_6_an_unknown_target_is_skipped(tags: tuple[str, ...]) -> None:
    assert decide(refining(), None) == Skip(reason="target_not_found")


@pytest.mark.parametrize("record_type", ["experience", "source", "assertion"])
def test_row_7_a_target_that_is_not_knowledge_is_skipped(record_type: str) -> None:
    assert decide(refining(), target(record_type=record_type)) == Skip(
        reason="target_not_knowledge"
    )


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("tags", [(), (MIGRATED_TAG,)])
def test_row_8_a_space_wide_target_is_skipped_in_every_status(
    status: str, tags: tuple[str, ...]
) -> None:
    assert decide(refining(), target(status=status, project=None, tags=tags)) == Skip(
        reason="target_space_wide"
    )


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("tags", [(), (MIGRATED_TAG,)])
def test_row_9_a_target_of_another_project_is_skipped_in_every_status(
    status: str, tags: tuple[str, ...]
) -> None:
    assert decide(refining(), target(status=status, project="other", tags=tags)) == Skip(
        reason="target_other_project"
    )


def test_row_10_a_proposed_target_of_the_project_is_revised_at_its_head() -> None:
    assert decide(refining(), target(status="proposed", revision=3)) == ReviseProposal(
        target_record_id=TARGET_ID, expected_revision=3
    )


def test_row_10_q018_a_migrated_proposed_target_is_kept_and_a_proposal_made() -> None:
    write = decide(refining(), target(status="proposed", tags=(MIGRATED_TAG,)))

    assert write == ProposeKnowledge(target_record_id=TARGET_ID, reason="migrated_target_kept")


@pytest.mark.parametrize("tags", [(), (MIGRATED_TAG,)])
@pytest.mark.parametrize("status", ["superseded", "retracted"])
def test_row_11_a_superseded_or_retracted_target_is_skipped(
    status: str, tags: tuple[str, ...]
) -> None:
    assert decide(refining(), target(status=status, tags=tags)) == Skip(
        reason="target_not_revisable"
    )


@pytest.mark.parametrize("tags", [(), (MIGRATED_TAG,)])
def test_row_12_an_accepted_target_of_the_project_gets_a_successor(tags: tuple[str, ...]) -> None:
    write = decide(refining(), target(status="accepted", tags=tags))

    assert write == ProposeSuccessor(target_record_id=TARGET_ID)


def test_row_12_without_assertions_it_is_a_proposal_that_names_the_target() -> None:
    write = decide(refining(), target(status="accepted"), assertions=False)

    assert write == ProposeKnowledge(
        target_record_id=TARGET_ID, reason="assertions unavailable: target not linked"
    )


@pytest.mark.parametrize("status", ["accepted", "superseded", "retracted", "proposed"])
def test_the_migrated_tag_matters_only_to_the_proposed_row(status: str) -> None:
    plain = decide(refining(), target(status=status))
    tagged = decide(refining(), target(status=status, tags=(MIGRATED_TAG,)))

    assert (plain == tagged) is (status != "proposed")


def test_no_row_yields_an_accept() -> None:
    kinds = {
        type(decide(refining(), target(status=status, tags=tags)))
        for status in STATUSES
        for tags in ((), (MIGRATED_TAG,))
    }

    assert kinds <= {ReviseProposal, ProposeKnowledge, ProposeSuccessor, Skip}


# ----- plan-level behaviour -----


def test_a_plan_skips_the_second_use_of_a_key() -> None:
    plan = CurationAdmissionPolicy().plan(
        [experience("e1"), experience("e1", body="again")], project_key=PROJECT, targets={}
    )

    assert plan.entries[0].write == RecordExperience()
    assert plan.entries[1].write == Skip(reason="malformed: key 'e1' is used twice")


def test_evidence_must_name_an_experience_candidate_of_the_plan() -> None:
    plan = CurationAdmissionPolicy().plan(
        [knowledge("k1", evidence=("k2",), reason="r"), knowledge("k2")],
        project_key=PROJECT,
        targets={},
    )

    assert plan.entries[0].write == Skip(
        reason="malformed: evidence key 'k2' names no experience candidate"
    )


def test_evidence_becomes_the_ordinals_of_the_experiences_that_were_recorded() -> None:
    plan = CurationAdmissionPolicy().plan(
        [knowledge("k1", evidence=("e1", "e2"), reason="seen"), experience("e1"), experience("e2")],
        project_key=PROJECT,
        targets={},
    )

    assert plan.entries[0].write == ProposeKnowledge(evidence_ordinals=(2, 3))


def test_evidence_naming_a_skipped_experience_plans_no_supports() -> None:
    plan = CurationAdmissionPolicy().plan(
        [experience("e1", subtype="rumour"), knowledge("k1", evidence=("e1",), reason="seen")],
        project_key=PROJECT,
        targets={},
    )

    assert plan.entries[1].write == ProposeKnowledge()


def test_without_assertions_evidence_is_validated_but_plans_no_supports() -> None:
    policy = CurationAdmissionPolicy(assertions_available=False)

    ok = policy.plan(
        [experience("e1"), knowledge("k1", evidence=("e1",), reason="seen")],
        project_key=PROJECT,
        targets={},
    )
    bad = policy.plan(
        [knowledge("k1", evidence=("nope",), reason="seen")], project_key=PROJECT, targets={}
    )

    assert ok.entries[1].write == ProposeKnowledge()
    assert isinstance(bad.entries[0].write, Skip)


def test_a_target_goes_through_the_targets_the_caller_read() -> None:
    plan = CurationAdmissionPolicy().plan(
        [refining()], project_key=PROJECT, targets={TARGET_ID: target(status="proposed")}
    )

    assert plan.entries[0].write == ReviseProposal(target_record_id=TARGET_ID, expected_revision=3)


def test_the_policy_never_reads_the_kind_of_a_skip_with_a_flaw_as_a_curator_skip() -> None:
    candidate = CurationCandidate(kind=CandidateKindEnum.SKIP, key="s", flaw="reason is not text")

    assert decide(candidate) == Skip(reason="malformed: reason is not text")


# ----- capture keys -----


def test_capture_keys_have_the_exact_documented_shapes() -> None:
    sk = "abc123"

    assert CaptureKeyPolicy.plan_key(sk) == "capture/abc123/plan"
    assert CaptureKeyPolicy.step_key(sk, 1, "experience") == "capture/abc123/1/experience"
    assert CaptureKeyPolicy.step_key(sk, 2, "knowledge") == "capture/abc123/2/knowledge"
    assert CaptureKeyPolicy.step_key(sk, 2, "revise") == "capture/abc123/2/revise"
    assert CaptureKeyPolicy.step_key(sk, 2, "supersedes") == "capture/abc123/2/supersedes"
    assert (
        CaptureKeyPolicy.step_key(sk, 3, CaptureKeyPolicy.supports_step(1))
        == "capture/abc123/3/supports-1"
    )


def test_ordinals_start_at_one() -> None:
    assert CaptureKeyPolicy.first_ordinal() == 1


def test_the_ticket_is_derived_from_the_submission_key() -> None:
    assert CaptureKeyPolicy.ticket_of("0123456789abcdef0123") == "0123456789abcdef"


# ----- progress -----

STAGED, PLANNED = CurationStageEnum.STAGED, CurationStageEnum.PLANNED
APPLYING, APPLIED = CurationStageEnum.APPLYING, CurationStageEnum.APPLIED


def test_the_forward_transitions_are_allowed() -> None:
    progress = CurationProgressPolicy.initial()
    assert progress.stage is STAGED

    for stage in (PLANNED, APPLYING, APPLIED):
        progress = CurationProgressPolicy.advance(progress, stage)
        assert progress.stage is stage


@pytest.mark.parametrize("stage", [STAGED, PLANNED, APPLYING])
def test_a_failure_records_where_and_why(stage: CurationStageEnum) -> None:
    start = CurationProgressPolicy.initial()
    for step in (PLANNED, APPLYING):
        if stage is not STAGED and start.stage is not stage:
            start = CurationProgressPolicy.advance(start, step)

    failed = CurationProgressPolicy.fail(
        start, CurationFailureReasonEnum.STEP_FAILED, error_code="KNOWLEDGE_007"
    )

    assert failed.stage is CurationStageEnum.FAILED
    assert failed.failed_at is stage
    assert failed.reason is CurationFailureReasonEnum.STEP_FAILED
    assert failed.error_code == "KNOWLEDGE_007"


def test_a_failed_ticket_returns_to_its_failed_at_stage() -> None:
    planned = CurationProgressPolicy.advance(CurationProgressPolicy.initial(), PLANNED)
    failed = CurationProgressPolicy.fail(planned, CurationFailureReasonEnum.STORE_UNAVAILABLE)

    assert CurationProgressPolicy.advance(failed, PLANNED) == planned
    assert CurationProgressPolicy.resume(failed) == planned


def test_resume_leaves_a_progress_that_did_not_fail_alone() -> None:
    staged = CurationProgressPolicy.initial()

    assert CurationProgressPolicy.resume(staged) is staged


def test_the_other_transitions_are_rejected() -> None:
    staged = CurationProgressPolicy.initial()
    applied = CurationProgressPolicy.advance(
        CurationProgressPolicy.advance(CurationProgressPolicy.advance(staged, PLANNED), APPLYING),
        APPLIED,
    )
    failed_at_staged = CurationProgressPolicy.fail(staged, CurationFailureReasonEnum.CURATOR_FAILED)

    with pytest.raises(InvalidCurationTransitionError):
        CurationProgressPolicy.advance(staged, APPLYING)
    with pytest.raises(InvalidCurationTransitionError):
        CurationProgressPolicy.advance(applied, STAGED)
    with pytest.raises(InvalidCurationTransitionError):
        CurationProgressPolicy.fail(applied, CurationFailureReasonEnum.STEP_FAILED)
    with pytest.raises(InvalidCurationTransitionError):
        CurationProgressPolicy.advance(failed_at_staged, PLANNED)
    with pytest.raises(InvalidCurationTransitionError):
        CurationProgressPolicy.fail(failed_at_staged, CurationFailureReasonEnum.STEP_FAILED)
