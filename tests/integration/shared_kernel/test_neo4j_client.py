"""Shared Neo4j client against the pinned Neo4j Community container (D-016).

These tests double as the record of what the pinned version does: constraint syntax, the
`SHOW CONSTRAINTS` shape, driver error mapping, races on a unique key and node write locks.
"""

import asyncio
from typing import Any

import pytest
from pydantic import SecretStr

from noesis.exceptions import (
    GraphStoreAuthenticationFailedError,
    GraphStoreBusyError,
    GraphStoreConstraintViolatedError,
    GraphStoreQueryFailedError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    Neo4jClient,
    Neo4jConnectionSettings,
    Neo4jTransaction,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

BLOCKED_PROBE_SECONDS: float = 0.5


async def _create_record_id_constraint(client: Neo4jClient) -> None:
    async with await client.begin() as transaction:
        await transaction.run(
            "CREATE CONSTRAINT record_id IF NOT EXISTS FOR (n:Record) REQUIRE n.id IS UNIQUE"
        )
        await transaction.commit()


async def _count_records(client: Neo4jClient, record_id: str) -> int:
    async with await client.begin() as transaction:
        rows: list[dict[str, Any]] = await transaction.run(
            "MATCH (n:Record {id: $id}) RETURN count(n) AS total", {"id": record_id}
        )
    return int(rows[0]["total"])


async def test_the_client_reaches_the_container(neo4j_settings: Neo4jConnectionSettings) -> None:
    async with Neo4jClient(neo4j_settings) as client:
        async with await client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run("RETURN 1 AS reached")
        assert rows == [{"reached": 1}]


async def test_committed_work_is_durable_and_uncommitted_work_is_rolled_back(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(neo4j_settings) as client:
        async with await client.begin() as committed:
            await committed.run("CREATE (:Record {id: 'kept'})")
            await committed.commit()
        async with await client.begin() as abandoned:
            await abandoned.run("CREATE (:Record {id: 'dropped'})")

        assert not abandoned.is_open
        assert await _count_records(client, "kept") == 1
        assert await _count_records(client, "dropped") == 0


async def test_single_property_uniqueness_constraints_work_in_community_and_are_idempotent(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(neo4j_settings) as client:
        await _create_record_id_constraint(client)
        await _create_record_id_constraint(client)  # IF NOT EXISTS: a no-op, no error

        async with await client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run("SHOW CONSTRAINTS")

    assert rows == [
        {
            "id": rows[0]["id"],
            "name": "record_id",
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": ["Record"],
            "properties": ["id"],
            "ownedIndex": "record_id",
            "propertyType": None,
        }
    ]


async def test_enterprise_only_constraints_are_rejected_by_community(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(neo4j_settings) as client, await client.begin() as transaction:
        with pytest.raises(GraphStoreQueryFailedError) as raised:
            await transaction.run(
                "CREATE CONSTRAINT x_key FOR (n:X) REQUIRE (n.a, n.b) IS NODE KEY"
            )

    assert (
        raised.value.metadata["neo4j_code"] == "Neo.DatabaseError.Schema.ConstraintCreationFailed"
    )


async def test_a_duplicate_key_is_a_constraint_violation_naming_label_and_property(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(neo4j_settings) as client:
        await _create_record_id_constraint(client)
        async with await client.begin() as transaction:
            await transaction.run("CREATE (:Record {id: 'r1'})")
            await transaction.commit()

        async with await client.begin() as transaction:
            with pytest.raises(GraphStoreConstraintViolatedError) as raised:
                await transaction.run("CREATE (:Record {id: 'r1'})")

    assert raised.value.error_code == "INTEGRATION_106_GRAPH_STORE_CONSTRAINT_VIOLATED"
    assert raised.value.metadata["label"] == "Record"
    assert raised.value.metadata["property"] == "id"
    assert (
        raised.value.metadata["neo4j_code"] == "Neo.ClientError.Schema.ConstraintValidationFailed"
    )
    assert raised.value.metadata["phase"] == "query"


async def test_racing_creates_of_one_unique_key_commit_once_and_the_loser_gets_the_violation(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(neo4j_settings) as client:
        await _create_record_id_constraint(client)
        first: Neo4jTransaction = await client.begin()
        second: Neo4jTransaction = await client.begin()
        await first.run("CREATE (:Record {id: 'race'})")

        loser: asyncio.Task[list[dict[str, Any]]] = asyncio.create_task(
            second.run("CREATE (:Record {id: 'race'})")
        )
        await asyncio.sleep(BLOCKED_PROBE_SECONDS)
        assert not loser.done()  # waits on the winner's index entry lock, not a blind insert
        await first.commit()

        with pytest.raises(GraphStoreConstraintViolatedError):
            await loser
        await second.close()

        assert await _count_records(client, "race") == 1


async def test_a_node_write_lock_blocks_a_second_locker_until_the_first_commits(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    lock: str = "MATCH (n:Record {id: 'locked'}) SET n._lock = true RETURN n.id AS id"
    async with Neo4jClient(neo4j_settings) as client:
        async with await client.begin() as setup:
            await setup.run("CREATE (:Record {id: 'locked'})")
            await setup.commit()
        holder: Neo4jTransaction = await client.begin()
        waiter: Neo4jTransaction = await client.begin()
        await holder.run(lock)

        blocked: asyncio.Task[list[dict[str, Any]]] = asyncio.create_task(waiter.run(lock))
        await asyncio.sleep(BLOCKED_PROBE_SECONDS)
        assert not blocked.done()
        await holder.run("MATCH (n:Record {id: 'locked'}) REMOVE n._lock")
        await holder.commit()

        assert await asyncio.wait_for(blocked, timeout=10) == [{"id": "locked"}]
        await waiter.close()


async def test_a_deadlock_is_reported_as_a_busy_store(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    write: str = "MATCH (n:Pair {id: $id}) SET n.touched = true"
    async with Neo4jClient(neo4j_settings) as client:
        async with await client.begin() as setup:
            await setup.run("CREATE (:Pair {id: 1}), (:Pair {id: 2})")
            await setup.commit()
        left: Neo4jTransaction = await client.begin()
        right: Neo4jTransaction = await client.begin()
        await left.run(write, {"id": 1})
        await right.run(write, {"id": 2})

        outcomes: list[list[dict[str, Any]] | BaseException] = await asyncio.gather(
            left.run(write, {"id": 2}), right.run(write, {"id": 1}), return_exceptions=True
        )
        await left.close()
        await right.close()

    busy: list[GraphStoreBusyError] = [
        outcome for outcome in outcomes if isinstance(outcome, GraphStoreBusyError)
    ]
    assert len(busy) == 1
    assert busy[0].metadata["neo4j_code"] == "Neo.TransientError.Transaction.DeadlockDetected"
    assert busy[0].error_code == "INTEGRATION_105_GRAPH_STORE_BUSY"


async def test_a_wrong_password_is_an_authentication_failure_without_the_password(
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    wrong: Neo4jConnectionSettings = neo4j_settings.model_copy(
        update={"password": SecretStr("not-the-password")}
    )

    async with Neo4jClient(wrong) as client:
        with pytest.raises(GraphStoreAuthenticationFailedError) as raised:
            await client.begin()

    assert raised.value.error_code == "INTEGRATION_104_GRAPH_STORE_AUTHENTICATION_FAILED"
    assert raised.value.metadata["neo4j_code"] == "Neo.ClientError.Security.Unauthorized"
    assert "not-the-password" not in str(raised.value)
    assert "not-the-password" not in repr(raised.value.metadata)


async def test_invalid_cypher_is_a_query_failure(neo4j_settings: Neo4jConnectionSettings) -> None:
    async with Neo4jClient(neo4j_settings) as client, await client.begin() as transaction:
        with pytest.raises(GraphStoreQueryFailedError) as raised:
            await transaction.run("RETURN 1 +")

    assert raised.value.metadata["neo4j_code"] == "Neo.ClientError.Statement.SyntaxError"
