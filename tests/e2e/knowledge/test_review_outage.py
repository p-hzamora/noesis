"""`noesis assertion|review` with Neo4j down (a closed local port), as real child processes.

AC-016 (fail closed for every command, within the connect timeout plus one second, NFR-004),
AC-023 and AC-028 (the user-presence refusal comes before any store access, so its code is not
`INTEGRATION_103`), AC-027 (the agent's bulk accept refusal likewise) and the controls that show
those refusals are specific. No container is needed: the port is closed.
"""

import socket
from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.support.noesis_process_support import run_noesis, store_environment
from tests.support.review_support import MIGRATED, env_agent, env_user

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = pytest.mark.integration

SPACE = "default"
CONNECT_TIMEOUT_SECONDS = 2
SLACK_SECONDS = 1.0
SECRET = "s3cret-pw-never-printed"
ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
OTHER_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
UNAVAILABLE = "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"

COMMANDS: dict[str, list[str]] = {
    "assertion propose": [
        "assertion",
        "propose",
        "--predicate",
        "supports",
        "--subject",
        ID,
        "--object",
        OTHER_ID,
        "--rationale",
        "because",
        "--source",
        "agent_session:s1",
        "--idempotency-key",
        "k",
    ],
    "assertion list": ["assertion", "list", "--about", ID],
    "review queue": ["review", "queue"],
    "review accept preview": ["review", "accept", ID, "--expected-revision", "1"],
    "review accept": [
        "review",
        "accept",
        ID,
        "--expected-revision",
        "1",
        "--yes",
        "--idempotency-key",
        "k",
    ],
    "review retract": [
        "review",
        "retract",
        ID,
        "--reason",
        "x",
        "--yes",
        "--idempotency-key",
        "k",
    ],
    "review log": ["review", "log", ID],
    "review repair preview": ["review", "repair"],
    "review repair": ["review", "repair", "--yes"],
    "review accept bulk preview": ["review", "accept", "--tag", MIGRATED, "--all"],
}


def _closed_port_uri() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"bolt://127.0.0.1:{probe.getsockname()[1]}"


@pytest.fixture
def closed_env(tmp_path: Path) -> dict[str, str]:
    """A child environment whose Neo4j is a closed port (a password is set, so only the port is wrong)."""
    settings = Neo4jConnectionSettings(
        uri=_closed_port_uri(), user="neo4j", password=SecretStr(SECRET)
    )
    return {
        **store_environment(tmp_path / "closed-home", SPACE, settings),
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": str(CONNECT_TIMEOUT_SECONDS),
    }


@pytest.fixture(scope="module")
def startup_seconds(tmp_path_factory: pytest.TempPathFactory) -> float:
    """Best of three `noesis --help` runs: interpreter and import cost, no store involved."""
    env = store_environment(
        tmp_path_factory.mktemp("startup-home"),
        SPACE,
        Neo4jConnectionSettings(uri="bolt://127.0.0.1:1", user="neo4j", password=SecretStr(SECRET)),
    )
    return min(run_noesis(["--help"], env, json_output=False).seconds for _ in range(3))


@pytest.mark.parametrize("argv", COMMANDS.values(), ids=COMMANDS)
def test_ac016_fail_closed_per_command(
    argv: list[str], closed_env: dict[str, str], startup_seconds: float
) -> None:
    result = run_noesis(argv, env_agent(closed_env))

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == UNAVAILABLE
    assert result.error["next_steps"]
    assert SECRET not in result.stdout + result.stderr
    bound = CONNECT_TIMEOUT_SECONDS + startup_seconds + SLACK_SECONDS
    assert result.seconds <= bound, f"{result.seconds:.2f}s > {bound:.2f}s"


APPLYING = {
    "accept": COMMANDS["review accept"],
    "retract": COMMANDS["review retract"],
    "bulk accept": ["review", "accept", "--tag", MIGRATED, "--all", "--yes"],
}


@pytest.mark.parametrize("argv", APPLYING.values(), ids=APPLYING)
def test_ac023_ac028_user_presence_required_comes_before_the_store(
    argv: list[str], closed_env: dict[str, str]
) -> None:
    """Standard input is `/dev/null`: the user is refused with the interface error, not INTEGRATION_103."""
    result = run_noesis(argv, env_user(closed_env))

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == "INTERFACE_006_USER_PRESENCE_REQUIRED"
    assert result.error["next_steps"]


CONTROLS = {
    "accept as agent without a terminal": (APPLYING["accept"], True),
    "retract as agent without a terminal": (APPLYING["retract"], True),
    "accept preview as user without a terminal": (COMMANDS["review accept preview"], False),
    "bulk preview as user without a terminal": (COMMANDS["review accept bulk preview"], False),
}


@pytest.mark.parametrize(("argv", "as_agent"), CONTROLS.values(), ids=CONTROLS)
def test_ac023_controls_reach_the_store(
    argv: list[str], as_agent: bool, closed_env: dict[str, str]
) -> None:
    env = env_agent(closed_env) if as_agent else env_user(closed_env)

    result = run_noesis(argv, env)

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == UNAVAILABLE


def test_ac027_bulk_accept_refused_for_agent_before_store_access(
    closed_env: dict[str, str],
) -> None:
    result = run_noesis(APPLYING["bulk accept"], env_agent(closed_env))

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert result.error["metadata"]["reason"] == "bulk_accept_requires_user"  # type: ignore[index]
    assert result.error["next_steps"]
    assert SECRET not in result.stdout + result.stderr
