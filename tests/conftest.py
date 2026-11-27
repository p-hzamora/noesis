"""Fixtures shared by every test: isolation from the real user configuration, and Neo4j."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.environment_support import drop_noesis_variables
from tests.support.neo4j_container import docker_unavailable_reason, running_neo4j, wipe_database

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

# Typer forces a Rich terminal when GITHUB_ACTIONS, FORCE_COLOR or PY_COLORS is set, and it reads
# this at import time; ANSI styling then splits option names like "--idempotency-key" in help text.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG (config, state, cache) and Claude Code folders at `tmp_path` and drop every NOESIS_* variable, for every test.

    The user's `~/.config/noesis` profiles become unreachable and no `NOESIS_NEO4J_*` value
    survives, so no test can reach the user's own Neo4j (NFR-004, AC-015).

    Returns:
        The fake home folder used for configuration and state.
    """
    home: Path = tmp_path / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))  # model cache (C5b)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)  # embedder sockets fall back to the cache
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
