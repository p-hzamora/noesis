"""`noesis index sync|status` over the `probe` projection: AC-011, AC-032 and the lock edges."""

import time

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.knowledge_support import NOW
from tests.support.noesis_process_support import capture_command, finish, run_noesis
from tests.support.retrieval.probe_process_support import (
    run_noesis_with_probe,
    start_noesis_with_probe,
)
from tests.support.retrieval.retrieval_neo4j_support import (
    capture_knowledge,
    revise_knowledge,
)
from tests.support.retrieval.retrieval_process_support import (
    head_sequence,
    probe_count,
    probe_cursor,
    probe_snapshot,
    revise_command,
    space_id_of,
    wait_until,
)
from tests.support.retrieval.status_writer import set_status_blocking

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

PROBE_DELAY_MS = 100
CAPTURES = 50
REVISES = 10


async def test_ac011_kill_and_rerun(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = space_id_of(neo4j_settings)
    assert run_noesis_with_probe(["index", "rebuild", "--yes"], child_env).code == 0
    record_ids = [
        await capture_knowledge(env, f"k-{number}", f"Record {number}")
        for number in range(CAPTURES)
    ]
    for number, record_id in enumerate(record_ids[:REVISES]):
        await revise_knowledge(env, record_id, f"r-{number}", expected=1, body=f"Revised {number}")
    head = head_sequence(neo4j_settings, space_id)
    assert head == CAPTURES + REVISES

    short_lock = {**child_env, "NOESIS_INDEX_LOCK_TTL_SECONDS": "2"}
    syncing = start_noesis_with_probe(["index", "sync"], short_lock, delay_ms=PROBE_DELAY_MS)
    wait_until(lambda: probe_count(neo4j_settings) >= 1, "the first probe entry", process=syncing)
    syncing.kill()
    syncing.communicate()
    assert probe_cursor(neo4j_settings, space_id) == 0, "the cursor must not advance mid-batch"
    # SIGKILL leaves the lock held; the rerun recovers through real TTL expiry
    rerun = run_noesis_with_probe(["index", "sync", "--wait-seconds", "10"], short_lock)
    after_sync = probe_snapshot(neo4j_settings)
    rebuilt = run_noesis_with_probe(["index", "rebuild", "--yes"], child_env)
    after_rebuild = probe_snapshot(neo4j_settings)

    assert rerun.code == 0, (rerun.stdout, rerun.stderr)
    assert rebuilt.code == 0, (rebuilt.stdout, rebuilt.stderr)
    assert len(after_sync) == CAPTURES
    assert after_sync == after_rebuild
    assert sum(1 for _, revision, _ in after_sync if revision == 2) == REVISES
    assert probe_cursor(neo4j_settings, space_id) == head


def test_ac032_probe_sync_and_status(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id = space_id_of(neo4j_settings)
    assert run_noesis_with_probe(["index", "rebuild", "--yes"], child_env).code == 0
    knowledge = run_noesis(capture_command("k", title="Alpha record"), child_env)
    experience = run_noesis(
        capture_command("e", record_type="experience", body="It broke."), child_env
    )
    knowledge_id = str(knowledge.result["record_id"])
    experience_id = str(experience.result["record_id"])
    assert run_noesis(revise_command(knowledge_id, "k-rev", "Second body."), child_env).code == 0
    set_status_blocking(
        neo4j_settings,
        space_id=space_id,
        record_id=knowledge_id,
        status="accepted",
        occurred_at=NOW,
    )

    synced = run_noesis_with_probe(["index", "sync"], child_env)
    status = run_noesis_with_probe(["index", "status", "--verify"], child_env)

    assert synced.code == 0, (synced.stdout, synced.stderr)
    (projection,) = synced.result["projections"]  # type: ignore[misc]
    assert (
        projection["kind"],
        projection["applied"],
        projection["skipped"],
        projection["cursor"],
    ) == (
        "probe",
        4,
        0,
        4,
    )
    assert probe_snapshot(neo4j_settings) == sorted(
        [
            (f"{space_id}:{knowledge_id}", 2, "accepted"),
            (f"{space_id}:{experience_id}", None, None),
        ]
    )
    assert status.code == 0, (status.stdout, status.stderr)
    (status_projection,) = status.result["projections"]  # type: ignore[misc]
    assert status_projection["lag"] == 0
    assert status_projection["divergences"] == []
    assert status.result["divergences"] == []

    query(
        neo4j_settings,
        "MATCH (p:IndexProbe {record_id: $record_id}) DETACH DELETE p",
        record_id=knowledge_id,
    )
    drifted = run_noesis_with_probe(["index", "status", "--verify"], child_env)

    (drifted_projection,) = drifted.result["projections"]  # type: ignore[misc]
    expected_divergence = [
        {"record_id": knowledge_id, "expected_revision": 2, "found_revision": None}
    ]
    assert drifted_projection["divergences"] == expected_divergence
    assert drifted.result["divergences"] == expected_divergence


async def test_a_second_sync_waits_then_reports_a_sync_in_progress(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    assert run_noesis_with_probe(["index", "rebuild", "--yes"], child_env).code == 0
    for number in range(30):
        await capture_knowledge(env, f"k-{number}", f"Record {number}")
    first = start_noesis_with_probe(["index", "sync"], child_env, delay_ms=200)
    wait_until(
        lambda: probe_count(neo4j_settings) >= 1, "the first sync holds the lock", process=first
    )

    second = run_noesis_with_probe(["index", "sync", "--wait-seconds", "1"], child_env)
    first_outcome = finish(first, time.monotonic())

    assert second.code == 1, (second.stdout, second.stderr)
    assert second.error["code"] == "RETRIEVAL_203_INDEX_SYNC_IN_PROGRESS"
    assert second.seconds >= 1.0
    assert first_outcome.code == 0, (first_outcome.stdout, first_outcome.stderr)
    assert probe_count(neo4j_settings) == 30


@pytest.mark.parametrize("command", ["status", "sync"])
async def test_a_registered_projection_that_was_never_rebuilt_is_not_initialised(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], command: str
) -> None:
    await capture_knowledge(env, "k", "Ports guide")

    index = run_noesis_with_probe(["index", command], child_env)
    search = run_noesis(["search", "ports", "--all-projects"], child_env)

    assert index.code == 1, (index.stdout, index.stderr)
    assert index.error["code"] == "RETRIEVAL_201_INDEX_NOT_INITIALISED"
    assert search.code == 0, (search.stdout, search.stderr)
    assert search.result["hits"]
