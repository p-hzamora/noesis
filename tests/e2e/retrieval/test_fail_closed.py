"""AC-005, Q-015 and NFR-007: a dead store fails closed; usage errors never contact it."""

from pathlib import Path

import pytest
from tests.support.noesis_process_support import run_noesis
from tests.support.retrieval.retrieval_process_support import SECRET, closed_store_environment

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

STORE_COMMANDS: dict[str, list[str]] = {
    "search": ["search", "ports"],
    "index sync": ["index", "sync"],
    "index rebuild": ["index", "rebuild", "--yes"],
    "index status": ["index", "status"],
}
USAGE_ERRORS: dict[str, list[str]] = {
    "limit zero": ["search", "ports", "--limit", "0"],
    "limit over fifty": ["search", "ports", "--limit", "51"],
    "empty query": ["search", ""],
    "project and all projects": ["search", "ports", "--project", "acme", "--all-projects"],
    "unregistered projection": ["index", "rebuild", "--projection", "probe", "--yes"],
}


@pytest.mark.parametrize("name", STORE_COMMANDS)
def test_ac005_every_command_fails_closed_on_a_closed_port(tmp_path: Path, name: str) -> None:
    """The production `noesis` reports `INTEGRATION_103`, exit 1, and never prints the password."""
    result = run_noesis(STORE_COMMANDS[name], closed_store_environment(tmp_path / "home"))

    assert result.code == 1, (result.stdout, result.stderr)
    assert result.error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert result.error["next_steps"]
    assert SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize("name", USAGE_ERRORS)
def test_usage_errors_exit_two_without_contacting_the_store(tmp_path: Path, name: str) -> None:
    """With the port closed, exit 2 (not 1/`INTEGRATION_103`) proves no store contact."""
    result = run_noesis(
        USAGE_ERRORS[name], closed_store_environment(tmp_path / "home"), json_output=False
    )

    assert result.code == 2, (result.stdout, result.stderr)
    assert "INTEGRATION_103" not in result.stdout + result.stderr
