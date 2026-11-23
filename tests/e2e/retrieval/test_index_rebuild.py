"""AC-010: a record captured while a rebuild runs is indexed by the sync that follows it."""

import time

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import finish, remember_command, run_noesis
from tests.support.retrieval.probe_process_support import start_noesis_with_probe
from tests.support.retrieval.retrieval_neo4j_support import capture_knowledge
from tests.support.retrieval.retrieval_process_support import (
    head_sequence,
    probe_count,
    probe_cursor,
    probe_snapshot,
    space_id_of,
    wait_until,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

RECORDS = 50
PROBE_DELAY_MS = 100


async def test_ac010_capture_during_rebuild(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    for number in range(RECORDS):
        await capture_knowledge(env, f"seed-{number}", f"Seed record {number}")
    space_id = space_id_of(neo4j_settings)

    rebuild = start_noesis_with_probe(
        ["index", "rebuild", "--yes"], child_env, delay_ms=PROBE_DELAY_MS
    )
    wait_until(
        lambda: probe_count(neo4j_settings) >= 1, "the probe holds its first entry", process=rebuild
    )
    started = time.monotonic()
    late = run_noesis(remember_command("late", title="Captured mid-rebuild"), child_env)
    still_running = rebuild.poll() is None
    outcome = finish(rebuild, started)

    assert late.code == 0, late.stdout
    assert still_running, "the capture finished after the rebuild: the scenario did not overlap"
    assert outcome.code == 0, (outcome.stdout, outcome.stderr)
    late_id = str(late.result["record_id"])
    assert (f"{space_id}:{late_id}", 1, "proposed") in probe_snapshot(neo4j_settings)
    assert len(probe_snapshot(neo4j_settings)) == RECORDS + 1
    assert probe_cursor(neo4j_settings, space_id) == head_sequence(neo4j_settings, space_id)
