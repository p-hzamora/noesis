"""The Knowledge curator adapter, driven against a fake `claude` executable."""

import json
from pathlib import Path

import pytest
from tests.support.curation_support import brief_contract
from tests.support.fake_claude import candidates_envelope, write_fake_claude

from noesis.bounded_context.knowledge.application.dtos import RelatedRecordDto
from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper
from noesis.bounded_context.knowledge.domain.value_objects import (
    DEFAULT_CURATION_SUBTYPES,
    CandidateKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
    default_system_prompt,
)
from noesis.exceptions import CuratorRunFailedError
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

SYSTEM_PROMPT: str = "You are a test curator."
BRIEF = WorkBriefMapper.to_domain(brief_contract())
E1: JsonObject = {
    "kind": "experience",
    "key": "e1",
    "subtype": "observation",
    "body": "Off by one.",
}
K1: JsonObject = {
    "kind": "knowledge",
    "key": "k1",
    "subtype": "convention",
    "title": "Offsets",
    "body": "Report the byte offset.",
    "evidence_keys": ["e1"],
    "reason": "seen",
}


def adapter(claude: Path, *, model: str = "", timeout: float = 10) -> ClaudeCliCuratorAdapter:
    return ClaudeCliCuratorAdapter(
        claude_bin=str(claude),
        model=model,
        max_budget_usd=0.25,
        timeout_seconds=timeout,
        system_prompt=SYSTEM_PROMPT,
        environment={"PATH": "/usr/bin:/bin"},
    )


async def test_structured_output_becomes_candidates_and_a_flawed_entry_keeps_its_place(
    tmp_path: Path,
) -> None:
    claude = write_fake_claude(
        tmp_path,
        envelope=candidates_envelope(
            [E1, {"kind": "poem", "key": "p"}, K1, {"kind": "skip", "key": "s", "reason": "in git"}]
        ),
    )

    candidates = await adapter(claude, model="haiku").judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)

    assert [c.key for c in candidates] == ["e1", "p", "k1", "s"]
    assert candidates[0].kind is CandidateKindEnum.EXPERIENCE
    assert candidates[1].kind is None and candidates[1].flaw is not None
    assert candidates[2].evidence_keys == ("e1",)
    assert candidates[3].kind is CandidateKindEnum.SKIP
    assert (tmp_path / "calls.log").read_text().count("\n") == 1


async def test_an_empty_candidates_list_is_a_valid_answer(tmp_path: Path) -> None:
    claude = write_fake_claude(tmp_path, envelope=candidates_envelope([]))

    assert await adapter(claude).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES) == ()


async def test_the_run_is_isolated_and_the_prompt_carries_the_brief_and_related_records(
    tmp_path: Path,
) -> None:
    claude = write_fake_claude(tmp_path, envelope=candidates_envelope([]))
    related = RelatedRecordDto(
        record_id="01HZZZZZZZZZZZZZZZZZZZZZZ1",
        record_type="knowledge",
        subtype="convention",
        title="Parser offset handling",
        status="proposed",
        project_key="c7-fixture",
        revision=1,
    )

    await adapter(claude, model="haiku").judge(BRIEF, [related], DEFAULT_CURATION_SUBTYPES)

    argv = (tmp_path / "argv.txt").read_text().split("\n")
    for flag in ("-p", "--no-session-persistence", "--json-schema", "--system-prompt"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--system-prompt") + 1] == SYSTEM_PROMPT
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "candidates" in schema["properties"]
    prompt = (tmp_path / "stdin.txt").read_text()
    assert "Harden the parser" in prompt and "fix parser offset" in prompt
    assert "01HZZZZZZZZZZZZZZZZZZZZZZ1" in prompt and "Parser offset handling" in prompt


async def test_the_recursion_guard_is_exported_to_the_child(tmp_path: Path) -> None:
    claude = write_fake_claude(tmp_path, envelope=candidates_envelope([]))

    await adapter(claude).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)

    assert json.loads((tmp_path / "env.json").read_text())["NOESIS_HOOK"] == "1"


async def test_no_model_flag_without_a_configured_model(tmp_path: Path) -> None:
    claude = write_fake_claude(tmp_path, envelope=candidates_envelope([]))

    await adapter(claude).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)

    assert "--model" not in (tmp_path / "argv.txt").read_text().split("\n")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "did not print JSON"),
        ("[]", "unexpected JSON shape"),
        (json.dumps({"subtype": "error_max_turns", "is_error": True}), "run failed"),
        (
            json.dumps({"subtype": "success", "is_error": False, "structured_output": {"x": 1}}),
            "no `candidates` list",
        ),
    ],
    ids=["not json", "not an object", "error envelope", "no candidates list"],
)
async def test_an_unusable_answer_is_a_curator_failure(
    tmp_path: Path, raw: str, message: str
) -> None:
    claude = write_fake_claude(tmp_path, raw=raw)

    with pytest.raises(CuratorRunFailedError, match=message) as raised:
        await adapter(claude).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)

    assert raised.value.error_code == "KNOWLEDGE_141_CURATOR_FAILED"


async def test_a_missing_binary_is_a_curator_failure_that_points_at_doctor(tmp_path: Path) -> None:
    with pytest.raises(CuratorRunFailedError) as raised:
        await adapter(tmp_path / "nowhere").judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)

    assert any("noesis doctor" in step for step in raised.value.next_steps)


async def test_a_run_that_exits_without_output_is_a_curator_failure(tmp_path: Path) -> None:
    claude = write_fake_claude(tmp_path, raw="", exit_code=3)

    with pytest.raises(CuratorRunFailedError, match="exited with 3"):
        await adapter(claude).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)


async def test_a_slow_run_times_out(tmp_path: Path) -> None:
    claude = write_fake_claude(tmp_path, envelope=candidates_envelope([]), sleep_seconds=5)

    with pytest.raises(CuratorRunFailedError, match="timed out"):
        await adapter(claude, timeout=0.5).judge(BRIEF, [], DEFAULT_CURATION_SUBTYPES)


def test_the_packaged_prompt_describes_the_candidates_shape_and_the_subtypes() -> None:
    prompt = default_system_prompt()

    assert '{"candidates": [...]}' in prompt
    for word in (
        "concept",
        "convention",
        "howto",
        "decision",
        "glossary",
        "observation",
        "outcome",
    ):
        assert word in prompt
    assert "manifest" not in prompt.lower() and "note kinds" not in prompt.lower()
