"""`noesis remember` as real child processes against the pinned Neo4j container."""

from pathlib import Path

import pytest
from tests.support.noesis_process_support import run_noesis, store_environment

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

COMMIT = "commit:" + "a" * 40


@pytest.fixture
def env(tmp_path: Path, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child environment for the wiped container, store initialised, space `e2e`."""
    child = store_environment(tmp_path / "child-home", "e2e", neo4j_settings)
    assert run_noesis(["store", "init"], child).code == 0
    return child


def _remember(title: str, body: str, *extra: str) -> list[str]:
    return [
        "remember",
        "--as",
        "knowledge",
        "--subtype",
        "decision",
        "--title",
        title,
        "--body",
        body,
        "--project",
        "demo",
        "--source",
        COMMIT,
        *extra,
    ]


def test_remember_refines(env: dict[str, str]) -> None:
    """The assertion part of AC-014: the new record refines another, as a proposed assertion."""
    target = run_noesis(_remember("Cards", "Pay with cards."), env)
    target_id = str(target.result["record_id"])

    refined = run_noesis(
        _remember(
            "Cards retry", "Pay with cards and retry declines twice.", "--refines", target_id
        ),
        env,
    )

    assert refined.code == 0, refined.stdout
    (assertion,) = refined.result["assertions"]  # type: ignore[misc]
    assert (assertion["predicate"], assertion["status"]) == ("refines", "proposed")
    listed = run_noesis(["assertion", "list", "--about", str(refined.result["record_id"])], env)
    assert listed.code == 0, listed.stdout
    assert [item["predicate"] for item in listed.result["assertions"]] == ["refines"]  # type: ignore[attr-defined]


def test_remember_check_writes_nothing_across_processes(env: dict[str, str]) -> None:
    checked = run_noesis(_remember("Retry", "Use retries.", "--check"), env)

    assert checked.code == 0 and checked.result["written"] is False
    assert "record_id" not in checked.result or checked.result["record_id"] is None
    stored = run_noesis(_remember("Retry", "Use retries."), env)
    assert stored.result["written"] is True and stored.result["replayed"] is False


def test_remember_usage_errors_exit_2_without_connecting(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings
) -> None:
    child = store_environment(tmp_path / "child-home", "e2e", neo4j_settings)
    argv = ["remember", "--as", "knowledge", "--body", "x"]

    assert run_noesis(argv, child).code == 2
