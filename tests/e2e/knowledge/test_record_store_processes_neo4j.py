"""`noesis record|store|doctor` as real child processes against the pinned Neo4j container.

Cross-process level of AC-001..AC-005, AC-008, AC-012, AC-019, AC-023 and NFR-003/NFR-004. The
in-process equivalents live in `tests/integration/interfaces/test_record_cli_neo4j.py`. Every
child gets an explicit minimal environment (`tests/support/noesis_process_support.py`).
"""

import socket
import time
from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.support.neo4j_container import admin_driver
from tests.support.noesis_process_support import (
    ProcessResult,
    capture_command,
    finish,
    remember_command,
    run_noesis,
    start_noesis,
    store_environment,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SPACE = "e2e"
CONNECT_TIMEOUT_SECONDS = 2
# NFR-003: a closed port fails within connect timeout + 1 s; the child's interpreter start-up is
# measured (`noesis --help`) and added, because it is not store latency.
NFR_003_SLACK_SECONDS = 1.0
SECRET = "s3cret-pw-never-printed"


@pytest.fixture
def env(tmp_path: Path, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child environment for the wiped container, space `e2e`."""
    return store_environment(tmp_path / "child-home", SPACE, neo4j_settings)


@pytest.fixture
def initialised(env: dict[str, str]) -> dict[str, str]:
    """`env` after `store init` ran in its own process."""
    assert run_noesis(["store", "init"], env).code == 0
    return env


def _closed_uri() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"bolt://127.0.0.1:{probe.getsockname()[1]}"


def _closed_settings(password: str) -> Neo4jConnectionSettings:
    return Neo4jConnectionSettings(uri=_closed_uri(), user="neo4j", password=SecretStr(password))


def _closed_env(tmp_path: Path) -> dict[str, str]:
    return {
        **store_environment(
            tmp_path / "closed-home",
            SPACE,
            _closed_settings(SECRET),
        ),
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": str(CONNECT_TIMEOUT_SECONDS),
    }


def _count(settings: Neo4jConnectionSettings, label: str) -> int:
    with admin_driver(settings) as driver:
        rows, _, _ = driver.execute_query(
            f"MATCH (n:{label}) RETURN count(n) AS c", database_=settings.database
        )
    return int(rows[0]["c"])


def _revise(record_id: str, key: str, body: str, expected: int = 1) -> list[str]:
    return [
        "record",
        "revise",
        record_id,
        "--expected-revision",
        str(expected),
        "--body",
        body,
        "--idempotency-key",
        key,
    ]


def test_capture_in_one_process_is_read_back_by_another_with_the_same_fields(
    env: dict[str, str],
) -> None:
    """AC-001: init, capture and get run in three separate processes."""
    assert run_noesis(["store", "init"], env).code == 0
    captured = run_noesis(remember_command("ac001"), env)
    record_id = str(captured.result["record_id"])
    fetched = run_noesis(["record", "get", record_id], env)

    assert captured.code == 0 and fetched.code == 0
    assert captured.result["revision"] == 1 and captured.result["status"] == "proposed"
    record = fetched.result
    assert record["id"] == record_id and record["head_revision"] == 1
    assert record["status"] == "proposed"
    assert record["revision"]["title"] == "Retry policy"  # type: ignore[index]
    assert record["revision"]["body"] == "Use retries."  # type: ignore[index]
    assert record["applicability"]["tags"] == ["area:retries"]  # type: ignore[index]
    assert record["sources"][0]["kind"] == "commit"  # type: ignore[index]


@pytest.mark.parametrize("round_number", range(5))
def test_two_processes_revising_the_same_head_yield_one_winner_and_one_conflict(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings, round_number: int
) -> None:
    """AC-002 / AC-023: both children are started before either is awaited."""
    record_id = str(
        run_noesis(remember_command(f"race-{round_number}"), initialised).result["record_id"]
    )

    started = time.monotonic()
    first = start_noesis(_revise(record_id, "rev-a", "Body A."), initialised)
    second = start_noesis(_revise(record_id, "rev-b", "Body B."), initialised)
    outcomes: list[ProcessResult] = [finish(first, started), finish(second, started)]

    winners = [o for o in outcomes if o.code == 0]
    losers = [o for o in outcomes if o.code == 1]
    assert len(winners) == 1 and len(losers) == 1, [(o.code, o.stdout, o.stderr) for o in outcomes]
    assert winners[0].result["revision"] == 2
    assert losers[0].error["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
    metadata = losers[0].error["metadata"]
    assert isinstance(metadata, dict)
    assert 1 in metadata.values() and 2 in metadata.values(), metadata  # expected 1, actual 2
    head = run_noesis(["record", "get", record_id], initialised).result
    assert head["head_revision"] == 2
    winning_body = "Body A." if outcomes[0].code == 0 else "Body B."
    assert head["revision"]["body"] == winning_body  # type: ignore[index]
    assert run_noesis(["record", "get", record_id, "--revision", "1"], initialised).code == 0
    assert run_noesis(["record", "get", record_id, "--revision", "3"], initialised).code == 1
    assert _count(neo4j_settings, "Revision") == 2


def test_two_processes_capturing_with_the_same_key_store_one_record(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    """AC-005: the idempotency race ends with both exit 0, one id and one record node."""
    started = time.monotonic()
    children = [start_noesis(remember_command("same-key"), initialised) for _ in range(2)]
    outcomes = [finish(child, started) for child in children]

    assert [o.code for o in outcomes] == [0, 0], [(o.stdout, o.stderr) for o in outcomes]
    ids = {str(o.result["record_id"]) for o in outcomes}
    assert len(ids) == 1
    assert sorted(o.result["replayed"] for o in outcomes) == [False, True]  # type: ignore[type-var]
    assert run_noesis(["record", "get", ids.pop()], initialised).code == 0
    assert _count(neo4j_settings, "Knowledge") == 1
    assert _count(neo4j_settings, "Revision") == 1
    assert _count(neo4j_settings, "IdempotencyKey") == 1
    assert _count(neo4j_settings, "Source") == 1


def test_a_replay_in_a_new_process_returns_the_first_record_and_a_changed_request_is_rejected(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    """AC-004 across processes."""
    first = run_noesis(remember_command("replay"), initialised)
    nodes_before = _count(neo4j_settings, "Knowledge"), _count(neo4j_settings, "Revision")
    again = run_noesis(remember_command("replay"), initialised)
    different = run_noesis(remember_command("replay", body="Another body."), initialised)

    assert again.code == 0
    assert again.result["record_id"] == first.result["record_id"]
    assert again.result["replayed"] is True
    assert (_count(neo4j_settings, "Knowledge"), _count(neo4j_settings, "Revision")) == nodes_before
    assert different.code == 1
    assert different.error["code"] == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"


def _startup_seconds(env: dict[str, str]) -> float:
    """Best of three `noesis --help` runs: interpreter and import cost, no store involved."""
    return min(run_noesis(["--help"], env, json_output=False).seconds for _ in range(3))


def test_every_store_command_fails_closed_and_fast_on_a_closed_port(tmp_path: Path) -> None:
    """AC-003 / NFR-003: INTEGRATION_103 within connect timeout + start-up + 1 s, no secret printed."""
    env = _closed_env(tmp_path)
    bound = CONNECT_TIMEOUT_SECONDS + _startup_seconds(env) + NFR_003_SLACK_SECONDS
    record_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    commands: dict[str, list[str]] = {
        "capture knowledge": remember_command("closed-1"),
        "capture experience": remember_command("closed-2", record_type="experience"),
        "revise": _revise(record_id, "closed-3", "x"),
        "get": ["record", "get", record_id],
        "store init": ["store", "init"],
    }

    for name, argv in commands.items():
        result = run_noesis(argv, env)

        assert result.code == 1, name
        assert result.error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE", name
        assert result.error["next_steps"], name
        assert SECRET not in result.stdout + result.stderr, name
        assert result.seconds <= bound, f"{name}: {result.seconds:.2f}s > {bound:.2f}s"


def test_wrong_password_is_an_authentication_failure_without_echoing_it(
    initialised: dict[str, str],
) -> None:
    wrong = {**initialised, "NOESIS_NEO4J_PASSWORD": SECRET}

    result = run_noesis(["record", "get", "01ARZ3NDEKTSV4RRFFQ69G5FAV"], wrong)

    assert result.code == 1
    assert result.error["code"] == "INTEGRATION_104_GRAPH_STORE_AUTHENTICATION_FAILED"
    assert SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize("command", ["capture", "revise"])
def test_a_missing_idempotency_key_is_a_usage_error_before_any_io(
    tmp_path: Path, command: str
) -> None:
    """Exit 2 with the store unreachable and no password: nothing was read or connected."""
    env = {
        **store_environment(tmp_path / "usage-home", SPACE, _closed_settings("x")),
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": "30",
    }
    del env["NOESIS_NEO4J_PASSWORD"]
    argv = capture_command("k")[:-2] if command == "capture" else _revise("X", "k", "b")[:-2]

    result = run_noesis(argv, env, json_output=False)

    assert result.code == 2, (result.stdout, result.stderr)
    assert result.seconds < 20


def test_revising_an_experience_is_a_typed_error(initialised: dict[str, str]) -> None:
    """AC-008."""
    experience = run_noesis(remember_command("exp", record_type="experience"), initialised)

    result = run_noesis(_revise(str(experience.result["record_id"]), "exp-rev", "x"), initialised)

    assert result.code == 1
    assert result.error["code"] == "KNOWLEDGE_207_RECORD_NOT_REVISABLE"


def _graph_check(result: ProcessResult) -> dict[str, object]:
    checks = result.result["checks"]
    assert isinstance(checks, list)
    return next(check for check in checks if check["name"] == "graph_store")


def test_doctor_reports_the_store_ok_with_its_steps_and_has_no_obsidian_check(
    initialised: dict[str, str],
) -> None:
    """AC-012 / AC-019."""
    result = run_noesis(["doctor"], initialised)

    check = _graph_check(result)
    assert check["ok"] is True
    assert "schema steps applied: core" in str(check["detail"])
    names = [str(c["name"]) for c in result.result["checks"]]  # type: ignore[union-attr]
    assert not [n for n in names if "obsidian" in n or "mcp" in n]


def test_doctor_reports_an_unreachable_store(tmp_path: Path) -> None:
    """AC-012 with the port closed."""
    env = _closed_env(tmp_path)

    check = _graph_check(run_noesis(["doctor"], env))

    assert check["ok"] is False
    assert "unreachable" in str(check["detail"])
    assert SECRET not in str(check)


@pytest.mark.parametrize(
    ("markers", "kind"),
    [
        (
            {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "7c9e6679-7425-40de-944b-e07fc1f90ae7"},
            "agent",
        ),
        ({}, "user"),
    ],
)
def test_the_stored_actor_follows_the_harness_markers_of_the_capturing_process(
    initialised: dict[str, str], markers: dict[str, str], kind: str
) -> None:
    """Markers are set explicitly on the child; the parent's own are never inherited."""
    captured = run_noesis(remember_command("actor"), {**initialised, **markers})

    stored = run_noesis(["record", "get", str(captured.result["record_id"])], initialised)

    actor = stored.result["revision"]["actor"]  # type: ignore[index]
    assert actor["kind"] == kind
    if kind == "agent":
        assert actor["session"] == markers["CLAUDE_CODE_SESSION_ID"]
    else:
        assert actor["session"] is None
