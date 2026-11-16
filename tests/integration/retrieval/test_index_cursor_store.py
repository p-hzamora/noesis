"""The Neo4j cursor store: lock expiry after a crash, and compare-and-set atomicity (D-014)."""

import asyncio

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import space_id_of

from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    Neo4jClient,
    Neo4jConnectionSettings,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

ROUNDS = 50
TTL_SECONDS = 1


async def test_a_lock_that_was_never_released_can_be_taken_after_its_ttl(
    env: Neo4jKnowledgeEnv,
) -> None:
    """The owner crashed: nobody released; the clock passes the 1 s TTL; the next acquire wins."""
    space_id: str = await space_id_of(env)
    store = Neo4jIndexCursorStoreAdapter(env.client, env.clock)

    assert await store.acquire("probe", space_id, "crashed-owner", TTL_SECONDS) is True
    assert await store.acquire("probe", space_id, "next-owner", TTL_SECONDS) is False
    env.clock.advance(TTL_SECONDS + 1)

    assert await store.acquire("probe", space_id, "next-owner", TTL_SECONDS) is True
    assert await store.acquire("probe", space_id, "crashed-owner", TTL_SECONDS) is False


async def test_a_released_lock_is_free_at_once(env: Neo4jKnowledgeEnv) -> None:
    space_id: str = await space_id_of(env)
    store = Neo4jIndexCursorStoreAdapter(env.client, env.clock)
    assert await store.acquire("probe", space_id, "first", 300) is True

    await store.release("probe", space_id, "first")

    assert await store.acquire("probe", space_id, "second", 300) is True


async def test_two_concurrent_acquires_on_one_cursor_have_exactly_one_winner_every_time(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    """Two clients (as two processes would) race 50 times; the winner releases between rounds."""
    space_id: str = await space_id_of(env)
    async with Neo4jClient(neo4j_settings) as other_client:
        stores = (
            Neo4jIndexCursorStoreAdapter(env.client, env.clock),
            Neo4jIndexCursorStoreAdapter(other_client, env.clock),
        )
        owners = ("owner-a", "owner-b")

        for round_number in range(ROUNDS):
            outcomes = await asyncio.gather(
                *(
                    store.acquire("probe", space_id, owner, 300)
                    for store, owner in zip(stores, owners, strict=True)
                )
            )

            assert sorted(outcomes) == [False, True], f"round {round_number}: {outcomes}"
            winner = owners[outcomes.index(True)]
            await stores[outcomes.index(True)].release("probe", space_id, winner)
