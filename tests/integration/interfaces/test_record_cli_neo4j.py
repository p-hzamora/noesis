"""`record`, `store` and `doctor` against the pinned Neo4j container, in-process.

Covers AC-001 (capture then get, here in one process; the cross-process proof is the
subprocess e2e), AC-004, AC-006, AC-011 and AC-012 at the CLI level.
"""

from pathlib import Path

import pytest
from tests.support.knowledge_cli_support import (
    COMMIT_SOURCE,
    capture_args,
    run_json,
    use_closed_store,
    use_store,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
ALL_STEPS = ["core", "review", "change_feed", "knowledge_fulltext", "retrieval_index"]


@pytest.fixture
def bare_store(
    neo4j_settings: Neo4jConnectionSettings, monkeypatch: pytest.MonkeyPatch
) -> Neo4jConnectionSettings:
    """An empty, uninitialised database the CLI is configured for."""
    use_store(monkeypatch, neo4j_settings)
    return neo4j_settings


@pytest.fixture
def store(bare_store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]) -> None:
    """The same database after `store init`."""
    code, _ = run_json(capsys, ["store", "init"])
    assert code == 0


def _result(envelope: dict[str, object]) -> dict[str, object]:
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


def _error(envelope: dict[str, object]) -> dict[str, object]:
    assert envelope["ok"] is False, envelope
    error = envelope["error"]
    assert isinstance(error, dict)
    return error


@pytest.mark.usefixtures("bare_store")
def test_store_init_twice_applies_the_steps_once_and_keeps_one_default_space(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, first = run_json(capsys, ["store", "init"])
    code_again, second = run_json(capsys, ["store", "init"])

    assert code == code_again == 0
    assert _result(first)["applied_steps"] == ALL_STEPS
    assert _result(first)["already_applied_steps"] == []
    assert _result(first)["default_space"]["created"] is True  # type: ignore[index]
    assert _result(second)["applied_steps"] == []
    assert _result(second)["already_applied_steps"] == ALL_STEPS
    assert _result(second)["default_space"]["created"] is False  # type: ignore[index]
    assert _result(second)["default_space"]["key"] == "personal"  # type: ignore[index]
    assert "schema_version" not in _result(first)


@pytest.mark.usefixtures("bare_store")
def test_store_init_in_text_mode_lists_the_steps(capsys: pytest.CaptureFixture[str]) -> None:
    from noesis.interfaces.cli import run

    assert run(["store", "init"]) == 0

    out: str = capsys.readouterr().out
    assert "applied steps: core" in out
    assert "default space: personal (created)" in out


@pytest.mark.usefixtures("bare_store")
def test_every_command_on_an_uninitialised_store_points_to_store_init(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for argv in (
        capture_args(),
        ["record", "get", MISSING_ID],
        [
            "record",
            "revise",
            MISSING_ID,
            "--expected-revision",
            "1",
            "--body",
            "x",
            "--idempotency-key",
            "k",
        ],
    ):
        code, envelope = run_json(capsys, argv)

        assert code == 1
        error = _error(envelope)
        assert error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
        assert error["metadata"] == {"missing_steps": ALL_STEPS}
        assert "Run `noesis store init`." in error["next_steps"]  # type: ignore[operator]


@pytest.mark.usefixtures("store")
def test_capture_then_get_returns_the_proposal_at_revision_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, captured = run_json(capsys, capture_args())
    record_id = str(_result(captured)["record_id"])

    assert code == 0
    assert _result(captured)["record_type"] == "knowledge"
    assert _result(captured)["revision"] == 1
    assert _result(captured)["status"] == "proposed"
    assert _result(captured)["replayed"] is False

    code, fetched = run_json(capsys, ["record", "get", record_id])
    record = _result(fetched)

    assert code == 0
    assert record["id"] == record_id
    assert record["status"] == "proposed" and record["head_revision"] == 1
    assert record["revision"]["title"] == "Retry policy"  # type: ignore[index]
    assert record["revision"]["body"] == "Use retries."  # type: ignore[index]
    assert record["applicability"]["tags"] == ["area:retries"]  # type: ignore[index]
    assert record["sources"][0]["kind"] == "commit"  # type: ignore[index]
    assert record["sources"][0]["locator"] == COMMIT_SOURCE.removeprefix("commit:")  # type: ignore[index]


@pytest.mark.usefixtures("store")
def test_the_actor_is_the_user_outside_a_harness_and_an_agent_inside_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("USER", "pablo")
    monkeypatch.setenv("LOGNAME", "pablo")
    _, by_user = run_json(capsys, capture_args("by-user"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-42")
    _, by_agent = run_json(capsys, capture_args("by-agent", body="Other text."))

    _, user_record = run_json(capsys, ["record", "get", str(_result(by_user)["record_id"])])
    _, agent_record = run_json(capsys, ["record", "get", str(_result(by_agent)["record_id"])])

    assert _result(user_record)["revision"]["actor"] == {  # type: ignore[index]
        "kind": "user",
        "name": "pablo",
        "session": None,
    }
    assert _result(agent_record)["revision"]["actor"] == {  # type: ignore[index]
        "kind": "agent",
        "name": "claude-code",
        "session": "session-42",
    }


@pytest.mark.usefixtures("store")
def test_the_same_key_and_request_returns_the_first_record_and_a_different_request_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, first = run_json(capsys, capture_args())
    code, again = run_json(capsys, capture_args())
    different_code, different = run_json(capsys, capture_args(body="Something else."))

    assert code == 0
    assert _result(again)["record_id"] == _result(first)["record_id"]
    assert _result(again)["replayed"] is True
    assert different_code == 1
    assert _error(different)["code"] == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"


@pytest.mark.usefixtures("store")
def test_revise_appends_a_revision_and_get_reads_each_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, captured = run_json(capsys, capture_args())
    record_id = str(_result(captured)["record_id"])
    revise = ["record", "revise", record_id, "--expected-revision", "1", "--body", "Use backoff."]

    code, revised = run_json(capsys, [*revise, "--idempotency-key", "rev-1"])
    stale_code, stale = run_json(capsys, [*revise, "--idempotency-key", "rev-2"])
    _, head = run_json(capsys, ["record", "get", record_id])
    _, first = run_json(capsys, ["record", "get", record_id, "--revision", "1"])

    assert code == 0
    assert _result(revised)["revision"] == 2
    assert stale_code == 1
    assert _error(stale)["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert _result(head)["revision"]["body"] == "Use backoff."  # type: ignore[index]
    assert _result(head)["revision"]["title"] == "Retry policy"  # type: ignore[index]
    assert _result(first)["revision"]["body"] == "Use retries."  # type: ignore[index]
    assert _result(first)["head_revision"] == 2


@pytest.mark.usefixtures("store")
def test_experience_capture_cites_an_existing_source_by_id_and_revise_rejects_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, knowledge = run_json(capsys, capture_args())
    _, fetched = run_json(capsys, ["record", "get", str(_result(knowledge)["record_id"])])
    source_id = str(_result(fetched)["sources"][0]["id"])  # type: ignore[index]

    code, experience = run_json(
        capsys,
        [
            "record",
            "capture",
            "--type",
            "experience",
            "--body",
            "Retries masked the outage.",
            "--subtype",
            "outcome",
            "--project",
            "demo",
            "--occurred",
            "2026-11-01T10:00:00",
            "--session",
            "s-9",
            "--environment",
            "ci",
            "--source-id",
            source_id,
            "--idempotency-key",
            "exp-1",
        ],
    )
    experience_id = str(_result(experience)["record_id"])
    _, stored = run_json(capsys, ["record", "get", experience_id])
    revise_code, revise = run_json(
        capsys,
        [
            "record",
            "revise",
            experience_id,
            "--expected-revision",
            "1",
            "--body",
            "x",
            "--idempotency-key",
            "rev-x",
        ],
    )

    assert code == 0
    assert _result(experience)["record_type"] == "experience"
    assert _result(stored)["subtype"] == "outcome"
    assert _result(stored)["session"] == "s-9" and _result(stored)["environment"] == "ci"
    assert _result(stored)["sources"][0]["id"] == source_id  # type: ignore[index]
    assert revise_code == 1
    assert _error(revise)["code"] == "KNOWLEDGE_207_RECORD_NOT_REVISABLE"


@pytest.mark.usefixtures("store")
def test_a_source_id_of_nothing_is_rejected_and_writes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [a for a in capture_args() if a not in ("--source", COMMIT_SOURCE)]
    code, envelope = run_json(capsys, [*argv, "--source-id", MISSING_ID])

    assert code == 1
    assert _error(envelope)["code"] == "KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE"


@pytest.mark.usefixtures("store")
def test_a_record_of_another_space_is_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, captured = run_json(capsys, capture_args())
    monkeypatch.setenv("NOESIS_KNOWLEDGE_SPACE", "other")
    run_json(capsys, ["store", "init"])

    code, envelope = run_json(capsys, ["record", "get", str(_result(captured)["record_id"])])

    assert code == 1
    assert _error(envelope)["code"] == "KNOWLEDGE_201_RECORD_NOT_FOUND"


@pytest.mark.usefixtures("store")
def test_body_dash_reads_stdin_and_secrets_are_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("token ghp_" + "a" * 36 + " leaked"))
    argv = capture_args()
    argv[argv.index("--body") + 1] = "-"

    code, captured = run_json(capsys, argv)
    _, fetched = run_json(capsys, ["record", "get", str(_result(captured)["record_id"])])

    assert code == 0
    body = str(_result(fetched)["revision"]["body"])  # type: ignore[index]
    assert body.startswith("token ") and body.endswith(" leaked")
    assert "ghp_" not in body


@pytest.mark.usefixtures("store")
def test_the_default_project_is_the_git_repository_name_of_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "my-repo"
    (repository / ".git").mkdir(parents=True)
    monkeypatch.chdir(repository)
    argv = capture_args()
    index = argv.index("--project")
    del argv[index : index + 2]

    _, captured = run_json(capsys, argv)
    _, project = run_json(capsys, ["record", "get", str(_result(captured)["project_id"])])

    assert _result(project)["type"] == "project"
    assert _result(project)["key"] == "my-repo"


def _check(envelope: dict[str, object], name: str) -> dict[str, object]:
    checks = _result(envelope)["checks"]
    assert isinstance(checks, list)
    return next(check for check in checks if check["name"] == name)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A vault and a `claude` executable, so only the store check can fail."""
    (tmp_path / "vault").mkdir()
    (tmp_path / "bin").mkdir()
    curator = tmp_path / "bin" / "claude"
    curator.write_text("#!/bin/sh\n", encoding="utf-8")
    curator.chmod(0o755)
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")


@pytest.mark.usefixtures("vault", "store")
def test_doctor_reports_the_store_reachable_with_its_applied_steps(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, envelope = run_json(capsys, ["doctor"])
    check = _check(envelope, "graph_store")

    assert code == 0
    assert check["ok"] is True
    assert "schema steps applied: core" in str(check["detail"])


@pytest.mark.usefixtures("vault", "bare_store")
def test_doctor_reports_an_uninitialised_store_with_the_missing_step(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, envelope = run_json(capsys, ["doctor"])
    check = _check(envelope, "graph_store")

    assert code == 1
    assert check["ok"] is False
    assert "missing: core" in str(check["detail"])
    assert check["next_step"] == "Run `noesis store init`."


@pytest.mark.usefixtures("vault", "bare_store")
def test_doctor_reports_rejected_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", "wrong-password")

    code, envelope = run_json(capsys, ["doctor"])
    check = _check(envelope, "graph_store")

    assert code == 1
    assert check["ok"] is False
    assert "credentials rejected" in str(check["detail"])
    assert "wrong-password" not in str(envelope)


@pytest.mark.usefixtures("vault")
def test_doctor_reports_an_unreachable_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    uri = use_closed_store(monkeypatch)

    code, envelope = run_json(capsys, ["doctor"])
    check = _check(envelope, "graph_store")

    assert code == 1
    assert check["ok"] is False
    assert f"unreachable at {uri}" == check["detail"]
    assert "NOESIS_NEO4J_URI" in str(check["next_step"])


@pytest.mark.usefixtures("vault")
def test_doctor_without_a_password_warns_and_keeps_its_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, envelope = run_json(capsys, ["doctor"])
    check = _check(envelope, "graph_store")

    assert code == 0
    assert check["ok"] is True and check["warning"] is True
    assert "NOESIS_NEO4J_PASSWORD" in str(check["detail"])


@pytest.mark.usefixtures("vault", "store")
def test_doctor_has_no_obsidian_check(capsys: pytest.CaptureFixture[str]) -> None:
    _, envelope = run_json(capsys, ["doctor"])

    names = [check["name"] for check in _result(envelope)["checks"]]  # type: ignore[union-attr]
    assert not [name for name in names if "obsidian" in str(name) or "mcp" in str(name)]
