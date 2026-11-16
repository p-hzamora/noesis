"""The anti-corruption edges: the work-brief mapper, the strict apply parser, the curator answer."""

import json

import pytest
from tests.support.curation_support import SECRET_GH, SHA1, SHA2, brief_contract

from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper
from noesis.bounded_context.knowledge.application.services.curation_redactor import (
    CurationRedactor,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    DEFAULT_CURATION_SUBTYPES,
    CandidateKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    parse_apply_payload,
    render_user_prompt,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation.candidate_answer_schema import (
    candidates_of_answer,
    response_json_schema,
)

pytestmark = pytest.mark.unit


def payload(*entries: object) -> str:
    return json.dumps({"candidates": list(entries)})


E1 = {"kind": "experience", "key": "e1", "subtype": "outcome", "body": "It worked."}
K1 = {
    "kind": "knowledge",
    "key": "k1",
    "subtype": "decision",
    "title": "Use X",
    "body": "Because Y.",
}


# ----- WorkBriefMapper -----


def test_the_mapper_copies_the_contract_field_by_field() -> None:
    brief = WorkBriefMapper.to_domain(brief_contract(goal="g", excerpt="x"))

    assert brief.session_id == "sess-c7-0001"
    assert brief.repository == "c7-fixture"
    assert brief.head == SHA2
    assert brief.commit_shas() == (SHA1, SHA2)
    assert (brief.goal, brief.excerpt, brief.contract_version) == ("g", "x", 1)


def test_redaction_masks_the_brief_before_the_submission_key_is_derived() -> None:
    leaky = WorkBriefMapper.to_domain(brief_contract(goal=f"fix {SECRET_GH}"))

    redacted = CurationRedactor.brief(leaky)

    assert SECRET_GH not in redacted.model_dump_json()
    assert "[REDACTED]" in redacted.goal
    assert redacted.submission_key() == leaky.submission_key()  # the goal is not in the key


# ----- the strict apply parser -----


def test_a_valid_payload_parses_into_candidates_in_order() -> None:
    parsed = parse_apply_payload(payload(E1, K1))

    assert parsed.rejected == ()
    assert [c.key for c in parsed.candidates] == ["e1", "k1"]
    assert parsed.candidates[0].kind is CandidateKindEnum.EXPERIENCE


def test_an_empty_candidates_list_is_a_valid_payload() -> None:
    parsed = parse_apply_payload(payload())

    assert parsed.candidates == () and parsed.rejected == ()


def test_every_flawed_entry_is_reported_with_its_index_and_a_reason() -> None:
    no_body = {"kind": "experience", "key": "e2", "subtype": "outcome"}
    parsed = parse_apply_payload(payload(E1, no_body, {"kind": "x"}, "text"))

    assert [(r.index, r.reason) for r in parsed.rejected] == [
        (1, "missing body"),
        (2, "kind: Input should be 'experience', 'knowledge' or 'skip'"),
        (3, "entry is not an object"),
    ]
    assert parsed.candidates == ()


def test_a_key_used_twice_and_a_bad_evidence_key_are_rejected_at_the_later_entry() -> None:
    k_bad = {**K1, "key": "k2", "evidence_keys": ["nope"], "reason": "seen"}
    parsed = parse_apply_payload(payload(E1, {**E1, "body": "again"}, k_bad))

    assert [(r.index, r.reason) for r in parsed.rejected] == [
        (1, "key 'e1' is used twice"),
        (2, "evidence key 'nope' names no experience candidate"),
    ]


def test_a_payload_that_is_not_json_is_rejected_without_an_index() -> None:
    parsed = parse_apply_payload("{not json")

    assert len(parsed.rejected) == 1
    assert parsed.rejected[0].index is None
    assert parsed.rejected[0].reason.startswith("not valid JSON")


@pytest.mark.parametrize(
    "text",
    ["[]", '{"decisions": []}', '{"candidates": {}}', '{"candidates": [], "extra": 1}'],
)
def test_the_envelope_must_be_an_object_with_a_single_candidates_list(text: str) -> None:
    parsed = parse_apply_payload(text)

    assert [r.index for r in parsed.rejected] == [None]
    assert "candidates" in parsed.rejected[0].reason


def test_an_unknown_field_is_a_flaw_and_the_reason_never_echoes_values() -> None:
    parsed = parse_apply_payload(payload({**E1, "body": SECRET_GH, "colour": "red"}))

    assert parsed.rejected[0].index == 0
    assert SECRET_GH not in parsed.rejected[0].reason


# ----- the curator answer, read leniently -----


def test_a_usable_answer_becomes_candidates_and_a_flawed_entry_keeps_its_position() -> None:
    answer = {"candidates": [E1, {"kind": "poem", "key": "p"}, 7, K1]}

    candidates = candidates_of_answer(answer)

    assert candidates is not None
    assert [c.key for c in candidates] == ["e1", "p", None, "k1"]
    assert candidates[1].kind is None and "unknown kind" in (candidates[1].flaw or "")
    assert candidates[2].flaw == "entry is not an object"
    assert candidates[3].entry_flaw() is None


def test_a_wrongly_typed_field_becomes_a_flaw_not_an_error() -> None:
    (candidate,) = (
        candidates_of_answer({"candidates": [{**E1, "body": 5, "evidence_keys": "e"}]}) or ()
    )

    assert "body is not text" in (candidate.flaw or "")
    assert "evidence_keys is not a list of text" in (candidate.flaw or "")


@pytest.mark.parametrize("answer", ["text", None, [], {"decisions": []}, {"candidates": "x"}])
def test_an_answer_without_a_candidates_list_is_unusable(answer: object) -> None:
    assert candidates_of_answer(answer) is None


def test_an_empty_answer_is_valid() -> None:
    assert candidates_of_answer({"candidates": []}) == ()


def test_the_schema_limits_the_subtype_to_the_allowed_set() -> None:
    schema = json.loads(response_json_schema(DEFAULT_CURATION_SUBTYPES))

    subtype = schema["$defs"]["CandidateEntryModel"]["properties"]["subtype"]
    assert set(subtype["enum"]) - {None} == (
        DEFAULT_CURATION_SUBTYPES.knowledge | DEFAULT_CURATION_SUBTYPES.experience
    )
    assert schema["properties"]["candidates"]["type"] == "array"


def test_the_prompt_lists_subtypes_the_brief_and_related_records_without_ownership() -> None:
    from noesis.bounded_context.knowledge.application.dtos import RelatedRecordDto

    brief = WorkBriefMapper.to_domain(brief_contract())
    related = RelatedRecordDto(
        record_id="01HZZZZZZZZZZZZZZZZZZZZZZ1",
        record_type="knowledge",
        subtype="convention",
        title="Parser offset handling",
        status="proposed",
        project_key="c7-fixture",
        revision=1,
    )

    text = render_user_prompt(brief, [related], DEFAULT_CURATION_SUBTYPES)

    assert "01HZZZZZZZZZZZZZZZZZZZZZZ1" in text and "Parser offset handling" in text
    assert "Harden the parser" in text and "howto" in text
    assert "ownership" not in text and "migrated" not in text
    assert "Related existing records: none." in render_user_prompt(
        brief, [], DEFAULT_CURATION_SUBTYPES
    )
    assert "ownership" not in RelatedRecordDto.model_fields
