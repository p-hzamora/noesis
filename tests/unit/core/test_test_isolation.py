"""The suite never sees the user's Neo4j settings (NFR-004, AC-015)."""

import os
from pathlib import Path

import pytest
from tests.support.environment_support import drop_noesis_variables

pytestmark = pytest.mark.unit


def test_no_noesis_neo4j_variable_reaches_a_test() -> None:
    assert [name for name in os.environ if name.startswith("NOESIS_NEO4J_")] == []


def test_the_user_profile_folder_is_replaced_by_a_temporary_one(tmp_path: Path) -> None:
    assert Path(os.environ["XDG_CONFIG_HOME"]).is_relative_to(tmp_path)


def test_the_guard_removes_neo4j_variables_set_in_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_URI", "bolt://user-store.example:7687")
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", "user-secret")

    drop_noesis_variables(monkeypatch)

    assert "NOESIS_NEO4J_URI" not in os.environ
    assert "NOESIS_NEO4J_PASSWORD" not in os.environ
