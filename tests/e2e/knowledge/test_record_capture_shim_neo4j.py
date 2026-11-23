"""The deprecated `record capture` forwards to `remember`: AC-011 and AC-016, as child processes."""

from pathlib import Path

import pytest
from tests.support.noesis_process_support import (
    capture_command,
    run_noesis,
    store_environment,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SHIM_FIELDS = {"record_id", "record_type", "revision", "status", "space_id", "replayed"}


@pytest.fixture
def env(tmp_path: Path, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child environment for the wiped container, store initialised, space `e2e`."""
    child = store_environment(tmp_path / "child-home", "e2e", neo4j_settings)
    assert run_noesis(["store", "init"], child).code == 0
    return child


def _remember_equivalent(key: str, title: str, body: str) -> list[str]:
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
        "--tag",
        "area:retries",
        "--source",
        "commit:" + "a" * 40,
        "--idempotency-key",
        key,
    ]


def test_remember_matches_capture(env: dict[str, str]) -> None:
    """AC-011: the same input stored by either command reads back with the same fields."""
    old = run_noesis(capture_command("k-old", title="Alpha policy", body="Alpha text."), env)
    new = run_noesis(_remember_equivalent("k-new", "Beta policy", "Beta text."), env)
    assert old.code == new.code == 0, (old.stdout, new.stdout)

    assert old.result["status"] == new.result["status"] == "proposed"
    assert old.result["revision"] == new.result["revision"] == 1
    assert old.result["record_type"] == new.result["record_type"]
    assert old.result["space_id"] == new.result["space_id"]
    assert old.result["project_id"] == new.result["project_id"]
    fetched_old = run_noesis(["record", "get", str(old.result["record_id"])], env).result
    fetched_new = run_noesis(["record", "get", str(new.result["record_id"])], env).result
    for field in ("status", "head_revision", "record_type", "applicability", "actor"):
        assert fetched_old.get(field) == fetched_new.get(field), field
    assert [s["kind"] for s in fetched_old["sources"]] == [
        s["kind"] for s in fetched_new["sources"]
    ]  # type: ignore[attr-defined]


def test_record_capture_shim(env: dict[str, str]) -> None:
    """AC-016: stdout keeps its shape, stderr names the replacement, the silence variable mutes it."""
    shim = run_noesis(capture_command("k-shim"), env)

    assert shim.code == 0, shim.stdout
    assert set(shim.result) >= SHIM_FIELDS
    assert "assertions" not in shim.result and "reconciliation" not in shim.result
    assert "DEPRECATED: use noesis remember" in shim.stderr

    replay = run_noesis(capture_command("k-shim"), env)
    assert replay.result["replayed"] is True
    assert replay.result["record_id"] == shim.result["record_id"]
    assert replay.stdout == shim.stdout.replace('"replayed": false', '"replayed": true')

    silent = run_noesis(capture_command("k-shim"), {**env, "NOESIS_SILENCE_DEPRECATION": "1"})
    assert silent.code == 0 and "DEPRECATED" not in silent.stderr
