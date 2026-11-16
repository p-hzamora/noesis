"""`noesis curate` against the pinned Neo4j container, in-process (a smoke of AC-001..AC-003, AC-006).

The curator is the fake `claude` executable; the related lookup is off. The full acceptance matrix
(AC-004..AC-017) belongs to the test-writer pass.
"""

import functools
from pathlib import Path

import pytest
from tests.support.curation_support import PROJECT, SESSION, SHA1, SHA2, brief_contract
from tests.support.fake_claude import candidates_envelope, write_fake_claude
from tests.support.knowledge_cli_support import run_json, use_store

from noesis.exceptions import InvalidRecordError
from noesis.interfaces.cli.commands import curate_commands
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

E1 = {"kind": "experience", "key": "e1", "subtype": "observation", "body": "Off by one on CRLF."}
K1 = {
    "kind": "knowledge",
    "key": "k1",
    "subtype": "convention",
    "title": "Parser errors carry the byte offset",
    "body": "Every parser error reports the byte offset.",
}


@pytest.fixture
def world(
    neo4j_settings: Neo4jConnectionSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Path:
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("NOESIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "off")
    folder = tmp_path / "claude"
    folder.mkdir()
    write_fake_claude(folder, envelope=candidates_envelope([E1, K1]))
    monkeypatch.setenv("NOESIS_CURATOR_CLAUDE_BIN", str(folder / "claude"))
    code, _ = run_json(capsys, ["store", "init"])
    assert code == 0
    return folder


def result_of(envelope: dict[str, object]) -> dict[str, object]:
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


def test_a_brief_lands_with_its_sources_and_the_same_brief_replays(
    world: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(brief_contract().model_dump_json(), encoding="utf-8")

    code, first = run_json(capsys, ["curate", "brief", "--brief-file", str(brief)])

    assert code == 0
    result = result_of(first)
    e1, k1 = result["items"]  # type: ignore[misc]
    assert (e1["outcome"], k1["outcome"], k1["status"], k1["revision"]) == (
        "recorded",
        "proposed",
        "proposed",
        1,
    )
    assert result["related_lookup"] == {"state": "disabled", "pending_changes": None}
    sources = [(s["kind"], s["locator"]) for s in result["sources"]]  # type: ignore[union-attr]
    assert sources == [
        ("work_brief", result["submission_key"]),
        ("commit", SHA1),
        ("commit", SHA2),
        ("agent_session", SESSION),
    ]
    code, got = run_json(capsys, ["record", "get", k1["record_id"]])
    record = result_of(got)
    assert record["project_id"] and record["status"] == "proposed"
    assert {(s["kind"], s["locator"]) for s in record["sources"]} == set(sources)  # type: ignore[union-attr]

    code, again = run_json(capsys, ["curate", "brief", "--brief-file", str(brief)])

    again_result = result_of(again)
    assert code == 0 and again_result["replayed"] is True
    assert [i["record_id"] for i in again_result["items"]] == [  # type: ignore[union-attr]
        e1["record_id"],
        k1["record_id"],
    ]
    assert (world / "calls.log").read_text().count("\n") == 1


def test_an_apply_without_a_commit_lands_with_the_session_and_work_brief_sources(
    world: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / PROJECT
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    payload = tmp_path / "p.json"
    payload.write_text(
        '{"candidates": [{"kind": "experience", "key": "e1", "subtype": "outcome", "body": "ok"}]}',
        encoding="utf-8",
    )

    code, envelope = run_json(
        capsys, ["curate", "apply", "--decisions-file", str(payload), "--session", "sess-c7-0002"]
    )

    result = result_of(envelope)
    assert code == 0
    assert [(s["kind"], s["locator"]) for s in result["sources"]] == [  # type: ignore[union-attr]
        ("work_brief", result["submission_key"]),
        ("agent_session", "sess-c7-0002"),
    ]
    assert not (world / "calls.log").exists()  # the curator is never called


def test_a_failure_after_the_first_write_keeps_its_id_when_the_ticket_is_retried(
    world: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failures = {"left": 1}

    async def hook(ordinal: int, step: str) -> None:
        if ordinal == 2 and failures["left"]:
            failures["left"] -= 1
            raise InvalidRecordError("injected step failure")

    monkeypatch.setattr(
        curate_commands,
        "open_curation",
        functools.partial(curate_commands.open_curation, step_hook=hook),
    )
    brief = tmp_path / "brief.json"
    brief.write_text(brief_contract().model_dump_json(), encoding="utf-8")

    code, failed = run_json(capsys, ["curate", "brief", "--brief-file", str(brief)])

    assert code == 1
    error = failed["error"]
    assert isinstance(error, dict) and error["code"] == "KNOWLEDGE_241_CURATION_FAILED"
    ticket = error["metadata"]["ticket"]
    _, parked = run_json(capsys, ["curate", "parked"])
    (entry,) = result_of(parked)["parked"]  # type: ignore[misc]
    assert (entry["stage"], entry["reason"]) == ("applying", "step_failed")

    code, retried = run_json(capsys, ["curate", "retry", ticket])

    assert code == 0
    items = result_of(retried)["items"]
    assert [i["outcome"] for i in items] == ["recorded", "proposed"]  # type: ignore[union-attr]
    assert (world / "calls.log").read_text().count("\n") == 1
