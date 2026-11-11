"""`noesis notes recall` with synthesis, end to end: a fake `claude` and, for the Obsidian case, a fake MCP server."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import briefing_envelope, write_fake_claude
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port
from tests.support.notes_support import note_file

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

PRIVACY = "repos/cv-generator/decisions/candidate-privacy.md"
GROUNDING = "repos/cv-generator/decisions/cv-grounding.md"
RUN = "repos/cv-generator/runs/2026-11-06-knowledge-base.md"
OTHER = "repos/other/decisions/privacy.md"
TASK = "Continue working on the cv-generator project while preserving candidate privacy and CV evidence grounding."
BRIEFING: JsonObject = {
    "summary": "Candidate data stays local and every CV claim needs evidence.",
    "constraints": [{"text": "Never send candidate data to a provider.", "sources": [PRIVACY]}],
    "decisions": [{"text": "Claims cite evidence.", "sources": [GROUNDING, "repos/x/invented.md"]}],
    "gotchas": [{"text": "Invented claim.", "sources": ["repos/x/invented.md"]}],
    "inferences": [{"text": "Export needs a gate.", "sources": [GROUNDING]}],
    "not_covered": ["deployment"],
}


def _note(path: str, title: str, updated: str, body: str) -> str:
    return note_file(path, title=title, updated=updated, body=body)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    notes: dict[str, str] = {
        PRIVACY: _note(
            PRIVACY, "Candidate privacy", "2026-11-03", "Candidate data never leaves the machine."
        ),
        GROUNDING: _note(GROUNDING, "CV grounding", "2026-11-03", "Every CV claim cites evidence."),
        RUN: _note(
            RUN, "Knowledge base", "2026-11-06", "Implemented the cv-generator knowledge base."
        ),
        OTHER: _note(OTHER, "Other privacy", "2026-11-03", "Candidate privacy elsewhere."),
    }
    for relative, text in notes.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(text, encoding="utf-8")
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_STATE_DIR", str(tmp_path / "state"))
    return folder


@pytest.fixture
def claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "fake-claude"
    folder.mkdir()
    write_fake_claude(folder, envelope=briefing_envelope(BRIEFING))
    monkeypatch.setenv("NOESIS_RECALL_CLAUDE_BIN", str(folder / "claude"))
    return folder


def _result(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: JsonObject = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True, envelope
    return envelope["result"]  # type: ignore[return-value]


def _recall(*extra: str) -> int:
    return run(["notes", "recall", TASK, "--repo", "cv-generator", *extra])


def test_the_default_is_a_grounded_briefing_not_a_list_of_paths(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _recall("--json") == 0

    result = _result(capsys)
    briefing: JsonObject = result["briefing"]  # type: ignore[assignment]
    assert result["synthesis"] == "briefing"
    assert briefing["constraints"] == [
        {"text": "Never send candidate data to a provider.", "sources": [PRIVACY]}
    ]
    assert briefing["decisions"][0]["sources"] == [GROUNDING]  # type: ignore[index]  # invented path dropped
    assert [item["text"] for item in briefing["unsupported"]] == ["Invented claim."]  # type: ignore[union-attr]
    assert briefing["inferences"][0]["text"] == "Export needs a gate."  # type: ignore[index]
    assert briefing["model"] == "claude-haiku-5-5"
    assert str(briefing["markdown"]).startswith("# Recall briefing: Continue working")
    assert {entry["path"] for entry in result["entries"]} <= {PRIVACY, GROUNDING, RUN}  # type: ignore[union-attr]
    assert OTHER not in {entry["path"] for entry in result["entries"]}  # type: ignore[union-attr]
    assert result["backend"] == "filesystem"
    assert any("set aside" in warning for warning in result["warnings"])  # type: ignore[union-attr]


def test_the_agent_received_the_full_notes_of_the_scoped_area_only(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _recall("--json") == 0

    sent: str = (claude / "stdin.txt").read_text()
    assert "Candidate data never leaves the machine." in sent  # body, not just a snippet
    assert "Candidate privacy elsewhere." not in sent  # other repository: out of scope
    assert "Task: Continue working" in sent


def test_text_mode_prints_the_markdown_briefing_and_the_notes_read(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _recall() == 0

    text: str = capsys.readouterr().out
    assert text.startswith("# Recall briefing: Continue working")
    assert f"- Never send candidate data to a provider. [`{PRIVACY}`]" in text
    assert "## Notes read" in text
    assert "model: claude-haiku-5-5" in text
    assert "backend: filesystem" in text
    assert "warning:" in text


def test_model_and_effort_from_the_environment_reach_the_runtime(
    vault: Path, claude: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_RECALL_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("NOESIS_RECALL_EFFORT", "low")

    assert _recall("--json") == 0

    argv: list[str] = (claude / "argv.txt").read_text().split("\n")
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    assert argv[argv.index("--effort") + 1] == "low"


def test_an_unknown_effort_level_is_rejected_before_anything_runs(
    vault: Path, claude: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_RECALL_EFFORT", "bogus")

    assert _recall("--json") == 1

    error: JsonObject = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "CORE_001_INVALID_CONFIGURATION"
    assert error["metadata"]["accepted"] == ["low", "medium", "high", "xhigh", "max"]  # type: ignore[index]
    assert not (claude / "argv.txt").exists()

    capsys.readouterr()
    assert _recall("--json", "--no-synthesis") == 0  # a recall-only typo does not break the rest


def test_no_synthesis_lists_the_notes_and_never_starts_the_agent(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _recall("--json", "--no-synthesis") == 0

    result = _result(capsys)
    assert (result["synthesis"], result["briefing"]) == ("digest", None)
    assert result["entries"]
    assert not (claude / "argv.txt").exists()


def test_no_matching_notes_is_exit_zero_with_no_evidence_and_no_model_call(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "recall", "kubernetes operator", "--repo", "cv-generator", "--json"]) == 0
    result = _result(capsys)
    assert (result["synthesis"], result["briefing"], result["entries"]) == ("no_evidence", None, [])
    assert not (claude / "argv.txt").exists()

    assert run(["notes", "recall", "kubernetes operator", "--repo", "cv-generator"]) == 0
    assert "no relevant notes" in capsys.readouterr().out


def test_an_unavailable_agent_fails_loudly_and_names_the_candidate_notes(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_RECALL_CLAUDE_BIN", str(vault / "no-such-claude"))

    assert _recall("--json") == 1

    error: JsonObject = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "NOTES_103_RECALL_AGENT_FAILED"
    assert PRIVACY in error["metadata"]["candidates"]  # type: ignore[operator,index]
    assert any("--no-synthesis" in step for step in error["next_steps"])  # type: ignore[union-attr]


def test_an_agent_that_answers_garbage_is_a_failure_not_an_empty_success(
    vault: Path, claude: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_fake_claude(claude, raw="I could not do that")

    assert _recall("--json") == 1

    assert json.loads(capsys.readouterr().out)["error"]["code"] == "NOTES_103_RECALL_AGENT_FAILED"


def test_the_reproduction_obsidian_matches_every_word_yet_recall_still_finds_the_notes(
    vault: Path, claude: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`recall` once returned ok with no entries here: one combined query matched no note."""
    with fake_obsidian_mcp(vault, all_words=True) as server:
        monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
        monkeypatch.setenv("NOESIS_WRITER_BACKEND", "mcp")
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", server.url)
        monkeypatch.delenv("NOESIS_VAULT_DIR")

        assert _recall("--json") == 0

        result = _result(capsys)
        searched: list[str] = [
            args["query"] for tool, args in server.calls if tool == "search_simple"
        ]
    assert "cv-generator" in searched and len(searched) > 1
    assert result["backend"] == "obsidian-mcp"
    assert result["synthesis"] == "briefing"
    assert {entry["path"] for entry in result["entries"]} >= {PRIVACY, GROUNDING}  # type: ignore[union-attr]
    assert "Candidate data never leaves the machine." in (claude / "stdin.txt").read_text()


def test_obsidian_closed_still_briefs_from_files_and_says_so(
    vault: Path, claude: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", f"http://127.0.0.1:{free_port()}/mcp/")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")

    assert _recall("--json") == 0

    result = _result(capsys)
    assert result["notice"] == "Obsidian MCP unreachable, searched files instead"
    assert (result["backend"], result["synthesis"]) == ("filesystem", "briefing")


def test_obsidian_closed_without_a_vault_fails_instead_of_reporting_no_evidence(
    vault: Path, claude: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
    monkeypatch.setenv("NOESIS_WRITER_BACKEND", "mcp")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", f"http://127.0.0.1:{free_port()}/mcp/")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")
    monkeypatch.delenv("NOESIS_VAULT_DIR")

    assert _recall("--json") == 1

    error: JsonObject = json.loads(capsys.readouterr().out)["error"]
    assert "unreachable" in str(error["message"])
    assert not (claude / "argv.txt").exists()
