"""The Claude CLI curator adapter, driven against a fake `claude` executable."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.notes_support import a_brief

from noesis.bounded_context.notes.application.mappers import WorkBriefMapper
from noesis.bounded_context.notes.domain.value_objects import CurationActionEnum, NoteKindEnum
from noesis.bounded_context.notes.infrastructure.outbound.curation import (
    ClaudeCliCuratorAdapter,
    default_system_prompt,
)
from noesis.exceptions import (
    CuratorFailedError,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)

pytestmark = pytest.mark.integration

SYSTEM_PROMPT: str = "You are a test curator."


def _adapter(claude: Path, *, model: str = "", timeout: float = 10) -> ClaudeCliCuratorAdapter:
    return ClaudeCliCuratorAdapter(
        claude_bin=str(claude),
        model=model,
        max_budget_usd=0.25,
        timeout_seconds=timeout,
        system_prompt=SYSTEM_PROMPT,
        environment={"PATH": "/usr/bin:/bin"},
    )


async def test_structured_output_becomes_domain_decisions(tmp_path: Path) -> None:
    skip: JsonObject = {"action": "skip", "candidate": "typo", "reason": "in git history"}
    bad_slug: JsonObject = {**TTL_DECISION, "slug": "Not A Slug", "candidate": "renamed"}
    no_title: JsonObject = {
        "action": "create",
        "candidate": "vague",
        "reason": "r",
        "kind": "decision",
    }
    claude: Path = write_fake_claude(
        tmp_path, envelope=success_envelope([TTL_DECISION, skip, bad_slug, no_title])
    )

    decisions = await _adapter(claude, model="haiku").curate(
        WorkBriefMapper.to_domain(a_brief()), []
    )

    assert [d.action for d in decisions] == [
        CurationActionEnum.CREATE,
        CurationActionEnum.SKIP,
        CurationActionEnum.CREATE,
        CurationActionEnum.SKIP,
    ]
    assert decisions[0].draft is not None and decisions[0].draft.kind is NoteKindEnum.DECISION
    assert decisions[2].draft is not None and decisions[2].draft.slug.value == "not-a-slug"
    assert decisions[3].reason == "malformed decision: missing kind or title"


async def test_the_run_is_isolated_and_receives_the_brief_on_stdin(tmp_path: Path) -> None:
    claude: Path = write_fake_claude(tmp_path, envelope=success_envelope([]))

    assert (
        await _adapter(claude, model="haiku").curate(WorkBriefMapper.to_domain(a_brief()), []) == ()
    )

    argv: list[str] = (tmp_path / "argv.txt").read_text().split("\n")
    for flag in ("-p", "--no-session-persistence", "--json-schema", "--system-prompt"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--system-prompt") + 1] == SYSTEM_PROMPT
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == ["decisions"]
    stdin: str = (tmp_path / "stdin.txt").read_text()
    assert '"repository": "demo"' in stdin
    assert "Related existing notes: none." in stdin


@pytest.mark.parametrize(
    ("envelope", "raw", "message"),
    [
        (None, "not json", "did not print JSON"),
        (None, "[1]", "unexpected JSON shape"),
        (
            {
                "type": "result",
                "subtype": "error_max_budget_usd",
                "is_error": True,
                "result": "budget",
            },
            None,
            "run failed",
        ),
        (
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "structured_output": {"nope": 1},
            },
            None,
            "did not match the schema",
        ),
    ],
)
async def test_unusable_answers_raise_curator_failed(
    tmp_path: Path, envelope: JsonObject | None, raw: str | None, message: str
) -> None:
    claude: Path = write_fake_claude(tmp_path, envelope=envelope, raw=raw)

    with pytest.raises(CuratorFailedError, match=message):
        await _adapter(claude).curate(WorkBriefMapper.to_domain(a_brief()), [])


async def test_missing_executable_timeout_and_crash_raise_curator_failed(tmp_path: Path) -> None:
    with pytest.raises(CuratorFailedError, match="Cannot start"):
        await _adapter(tmp_path / "missing").curate(WorkBriefMapper.to_domain(a_brief()), [])

    slow: Path = write_fake_claude(tmp_path, envelope=success_envelope([]), sleep_seconds=5)
    with pytest.raises(CuratorFailedError, match="timed out"):
        await _adapter(slow, timeout=0.5).curate(WorkBriefMapper.to_domain(a_brief()), [])

    crashing: Path = write_fake_claude(tmp_path, raw="", exit_code=3)
    with pytest.raises(CuratorFailedError, match="exited with 3"):
        await _adapter(crashing).curate(WorkBriefMapper.to_domain(a_brief()), [])


def test_the_packaged_system_prompt_ships_with_the_adapter() -> None:
    prompt: str = default_system_prompt()

    assert prompt.startswith("You are the curator of a personal engineering knowledge base.")
