"""Fixtures shared by every test: isolation from the real user configuration, and Neo4j."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.environment_support import drop_noesis_variables
from tests.support.neo4j_container import docker_unavailable_reason, running_neo4j, wipe_database

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG and Claude Code folders at `tmp_path` and drop every NOESIS_* variable, for every test.

    The user's `~/.config/noesis` profiles become unreachable and no `NOESIS_NEO4J_*` value
    survives, so no test can reach the user's own Neo4j (NFR-004, AC-015).

    Returns:
        The fake home folder used for configuration and state.
    """
    home: Path = tmp_path / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    drop_noesis_variables(monkeypatch)
    for name in (
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CODEX_HOME",
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "AI_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)
    # a test that forgets to fake the recall agent fails fast instead of calling a real model
    monkeypatch.setenv("NOESIS_RECALL_CLAUDE_BIN", str(tmp_path / "no-claude-here"))
    return home


@pytest.fixture(autouse=True)
def offline_update_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `doctor` and `update check` inspect a folder that is no checkout, so no test reaches the network.

    Tests of the update check override this with the checkout they built.
    """
    monkeypatch.setattr(
        "noesis.interfaces.cli.bootstrap.diagnostics_handlers_builder.installed_package_dir",
        lambda: tmp_path,
    )


@pytest.fixture(scope="session")
def neo4j_container() -> Iterator[Neo4jConnectionSettings]:
    """Start the pinned Neo4j image once per session; skip when Docker is absent (D-022).

    Yields:
        How to reach the container; never the user's configured store.
    """
    if reason := docker_unavailable_reason():
        pytest.skip(reason)
    with running_neo4j() as settings:
        yield settings


@pytest.fixture
def neo4j_settings(neo4j_container: Neo4jConnectionSettings) -> Neo4jConnectionSettings:
    """The session's Neo4j, emptied of nodes, constraints and indexes before the test.

    Returns:
        Connection settings for the wiped container database.
    """
    wipe_database(neo4j_container)
    return neo4j_container
