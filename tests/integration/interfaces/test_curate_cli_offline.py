"""`noesis curate` without a reachable store: usage errors, parking and listing, fail-closed.

The wiring is the real one (in-process `run`); the curator is a fake `claude` executable and the
store is a closed local port, so nothing here needs Docker.
"""

import json
from pathlib import Path

import pytest
from tests.support.curation_support import PROJECT, SESSION, brief_contract
from tests.support.fake_claude import candidates_envelope, write_fake_claude
from tests.support.knowledge_cli_support import run_json, use_closed_store

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "state"
    monkeypatch.setenv("NOESIS_STATE_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


@pytest.fixture
def claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "claude"
    folder.mkdir()
    write_fake_claude(
        folder,
        envelope=candidates_envelope(
            [{"kind": "experience", "key": "e1", "subtype": "observation", "body": "Off by one."}]
        ),
    )
    monkeypatch.setenv("NOESIS_CURATOR_CLAUDE_BIN", str(folder / "claude"))
    return folder


@pytest.fixture
def brief_file(tmp_path: Path) -> Path:
    path = tmp_path / "brief.json"
    path.write_text(brief_contract().model_dump_json(), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / PROJECT
    (folder / ".git").mkdir(parents=True)
    monkeypatch.chdir(folder)
    return folder


def test_a_down_store_parks_the_brief_before_any_judging_and_parked_lists_it(
    state: Path,
    claude: Path,
    brief_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "off")

    code, envelope = run_json(capsys, ["curate", "brief", "--brief-file", str(brief_file)])

    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    ticket = error["metadata"]["ticket"]
    assert any(f"noesis curate retry {ticket}" in step for step in error["next_steps"])
    assert not (claude / "calls.log").exists()

    monkeypatch.delenv("NOESIS_NEO4J_PASSWORD")  # listing needs neither the store nor a password
    code, listed = run_json(capsys, ["curate", "parked"])
    assert code == 0
    result = listed["result"]
    assert isinstance(result, dict)
    (entry,) = result["parked"]
    assert (entry["ticket"], entry["stage"], entry["reason"], entry["repository"]) == (
        ticket,
        "staged",
        "store_unavailable",
        PROJECT,
    )
    assert entry["age_seconds"] >= 0 and entry["parked_at"]


def test_the_same_down_store_failure_is_reported_again_for_a_retry_and_the_ticket_stays(
    state: Path,
    brief_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "off")
    run_json(capsys, ["curate", "brief", "--brief-file", str(brief_file)])
    _, listed = run_json(capsys, ["curate", "parked"])
    ticket = listed["result"]["parked"][0]["ticket"]  # type: ignore[index]

    code, envelope = run_json(capsys, ["curate", "retry", ticket])

    assert code == 1
    assert envelope["error"]["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"  # type: ignore[index]
    _, again = run_json(capsys, ["curate", "parked"])
    assert [p["ticket"] for p in again["result"]["parked"]] == [ticket]  # type: ignore[index]


def test_retry_all_without_yes_only_lists_and_changes_no_file(
    state: Path,
    claude: Path,
    brief_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "off")
    run_json(capsys, ["curate", "brief", "--brief-file", str(brief_file)])
    files = {p: p.read_text() for p in (state / "knowledge/curation").glob("*.json")}

    code, envelope = run_json(capsys, ["curate", "retry", "--all"])

    assert code == 0
    result = envelope["result"]
    assert isinstance(result, dict) and result["executed"] is False
    assert [t["outcome"] for t in result["tickets"]] == ["pending"]
    assert files == {p: p.read_text() for p in (state / "knowledge/curation").glob("*.json")}
    assert not (claude / "calls.log").exists()


def test_retry_all_with_yes_reports_each_ticket_and_exits_1_when_one_fails_again(
    state: Path,
    brief_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "off")
    run_json(capsys, ["curate", "brief", "--brief-file", str(brief_file)])

    code, envelope = run_json(capsys, ["curate", "retry", "--all", "--yes"])

    assert code == 1
    result = envelope["result"]
    assert isinstance(result, dict) and result["failed"] == 1
    (item,) = result["tickets"]
    assert item["outcome"] == "failed"
    assert item["error"]["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


def test_parked_with_an_empty_inbox_lists_nothing(
    state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, envelope = run_json(capsys, ["curate", "parked"])

    assert (code, envelope["result"]) == (0, {"parked": []})


def test_an_unknown_ticket_is_reported_with_the_listing_as_next_step(
    state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)

    code, envelope = run_json(capsys, ["curate", "retry", "no-such-ticket"])

    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict) and error["code"] == "KNOWLEDGE_242_PARKED_CURATION_NOT_FOUND"
    assert any("noesis curate parked" in step for step in error["next_steps"])


@pytest.mark.parametrize("argv", [["curate", "retry"], ["curate", "retry", "t1", "--all"]])
def test_retry_needs_exactly_a_ticket_or_all(argv: list[str]) -> None:
    assert run(argv) == 2


def test_a_brief_that_does_not_match_the_contract_is_a_usage_error_that_stages_nothing(
    state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"session_id": "s"}), encoding="utf-8")

    code, envelope = run_json(capsys, ["curate", "brief", "--brief-file", str(bad)])

    assert code == 2
    assert envelope["error"]["code"] == "INTERFACE_001_INVALID_WORK_BRIEF"  # type: ignore[index]
    assert not (state / "knowledge").exists()


def test_apply_outside_a_git_repository_stages_nothing(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    payload = tmp_path / "p.json"
    payload.write_text('{"candidates": []}', encoding="utf-8")

    code, envelope = run_json(
        capsys, ["curate", "apply", "--decisions-file", str(payload), "--session", "s"]
    )

    assert code == 2
    assert envelope["error"]["code"] == "INTERFACE_002_NOT_IN_GIT_REPOSITORY"  # type: ignore[index]
    assert not (state / "knowledge").exists()


def test_apply_without_a_session_and_with_no_harness_marker_is_a_usage_error(
    state: Path, repo: Path, tmp_path: Path
) -> None:
    payload = tmp_path / "p.json"
    payload.write_text('{"candidates": []}', encoding="utf-8")

    assert run(["curate", "apply", "--decisions-file", str(payload)]) == 2
    assert not (state / "knowledge").exists()


def test_a_flawed_payload_is_kept_redacted_and_reported_entry_by_entry(
    state: Path,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)  # the rejection happens before the store is touched
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    payload = tmp_path / "p.json"
    payload.write_text(
        json.dumps(
            {
                "candidates": [
                    {"kind": "experience", "key": "e1", "subtype": "outcome", "body": secret},
                    {"kind": "experience", "key": "e2", "subtype": "outcome"},
                ]
            }
        ),
        encoding="utf-8",
    )

    code, envelope = run_json(
        capsys, ["curate", "apply", "--decisions-file", str(payload), "--session", SESSION]
    )

    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict) and error["code"] == "KNOWLEDGE_243_CURATION_REJECTED"
    assert error["metadata"]["rejected"] == [{"index": 1, "reason": "missing body"}]
    kept = Path(error["metadata"]["kept_file"])
    assert kept.is_file() and secret not in kept.read_text()
    assert not list((state / "knowledge/curation").glob("*.json"))  # no ticket

    code, _ = run_json(
        capsys,
        ["curate", "apply", "--decisions-file", str(payload), "--session", SESSION, "--dry-run"],
    )
    assert code == 1
    assert len(list((state / "knowledge/curation/rejected").glob("*.json"))) == 1  # not kept again


def test_a_payload_that_is_not_json_is_rejected_without_an_index(
    state: Path,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_closed_store(monkeypatch)
    payload = tmp_path / "p.json"
    payload.write_text("{nope", encoding="utf-8")

    code, envelope = run_json(
        capsys, ["curate", "apply", "--decisions-file", str(payload), "--session", SESSION]
    )

    assert code == 1
    (rejected,) = envelope["error"]["metadata"]["rejected"]  # type: ignore[index]
    assert rejected["index"] is None


def test_a_bogus_related_lookup_setting_is_a_settings_error_before_any_io(
    state: Path,
    brief_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_CURATOR_RELATED_LOOKUP", "bogus")

    code, envelope = run_json(capsys, ["curate", "brief", "--brief-file", str(brief_file)])

    assert code == 1
    problems = str(envelope["error"]["metadata"]["problems"])  # type: ignore[index]
    assert "NOESIS_CURATOR_RELATED_LOOKUP" in problems
    assert not (state / "knowledge").exists()
