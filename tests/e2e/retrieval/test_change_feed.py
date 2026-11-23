"""AC-007: concurrent captures get distinct, consecutive, gap-free sequences."""

import time

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, query
from tests.support.noesis_process_support import finish, remember_command, start_noesis
from tests.support.retrieval.retrieval_process_support import head_sequence, space_id_of

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

ROUNDS = 5


def test_ac007(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    """Five rounds of two simultaneous capture processes: sequences 1..10, one per record."""
    captured: set[str] = set()
    for round_number in range(ROUNDS):
        started = time.monotonic()
        children = [
            start_noesis(
                remember_command(f"race-{round_number}-{side}", title=f"Race {side}"), child_env
            )
            for side in "ab"
        ]
        outcomes = [finish(child, started) for child in children]

        assert [outcome.code for outcome in outcomes] == [0, 0], [o.stderr for o in outcomes]
        captured |= {str(outcome.result["record_id"]) for outcome in outcomes}

    space_id = space_id_of(neo4j_settings)
    rows = query(
        neo4j_settings,
        "MATCH (c:Change {space_id: $space_id}) RETURN c.sequence AS sequence, "
        "c.record_id AS record_id, c.change_kind AS kind ORDER BY sequence",
        space_id=space_id,
    )
    assert [row["sequence"] for row in rows] == list(range(1, 2 * ROUNDS + 1))
    assert {row["record_id"] for row in rows} == captured
    assert {row["kind"] for row in rows} == {"created"}
    assert head_sequence(neo4j_settings, space_id) == 2 * ROUNDS
