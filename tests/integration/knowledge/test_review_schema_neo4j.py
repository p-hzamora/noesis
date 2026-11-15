"""The `review` schema step against the pinned Neo4j (AC-017) and the Neo4j facts the design leans on."""

import asyncio

import pytest
from neo4j.exceptions import ConstraintError
from tests.support.knowledge_cli_support import run_json, use_store
from tests.support.knowledge_neo4j_support import make_neo4j_env, query
from tests.support.knowledge_support import DEFAULT_SPACE_KEY
from tests.support.neo4j_container import admin_driver
from tests.support.review_support import ReviewNeo4jEnv, graph_digest, make_review_neo4j_env

from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

_SHOW = (
    "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
    "RETURN name, type, entityType, labelsOrTypes, properties"
)


def _constraints(settings: Neo4jConnectionSettings) -> dict[str, dict[str, object]]:
    return {row["name"]: row for row in query(settings, _SHOW)}  # type: ignore[arg-type]


def _applied_steps(settings: Neo4jConnectionSettings) -> list[str]:
    rows = query(settings, "MATCH (m:StoreMeta) RETURN m.applied_steps AS steps")
    assert len(rows) == 1
    return list(rows[0]["steps"])


async def test_ac017_review_schema_step(neo4j_settings: Neo4jConnectionSettings) -> None:
    """The `review` step adds exactly two single-property uniqueness constraints, once."""
    core_only = make_neo4j_env(neo4j_settings)
    try:
        await core_only.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
    finally:
        await core_only.client.close()
    before = _constraints(neo4j_settings)
    assert _applied_steps(neo4j_settings) == ["core"]

    env = make_review_neo4j_env(neo4j_settings)
    try:
        first = await env.base.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
        after_first = _constraints(neo4j_settings)
        second = await env.base.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
    finally:
        await env.client.close()
    after_second = _constraints(neo4j_settings)

    added = {name: row for name, row in after_first.items() if name not in before}
    assert sorted((row["labelsOrTypes"][0], row["properties"][0]) for row in added.values()) == [  # type: ignore[index]
        ("Assertion", "live_key"),
        ("Decision", "decision_key"),
    ]
    assert len(added) == 2
    for row in added.values():
        assert row["entityType"] == "NODE"
        assert len(row["labelsOrTypes"]) == 1 and len(row["properties"]) == 1  # type: ignore[arg-type]
        assert row["type"] == "UNIQUENESS"  # exact string to verify against the pinned Neo4j
    assert first.applied_steps == ("review",)
    assert second.applied_steps == () and second.already_applied_steps == ("core", "review")
    assert after_second == after_first
    assert _applied_steps(neo4j_settings) == ["core", "review"]


def test_ac017_store_without_the_review_step_is_not_initialised_for_review(
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A store initialised by a core-only registry: `review queue` names `review`, nothing written."""

    async def init_core_only() -> None:
        core_only = make_neo4j_env(neo4j_settings)
        try:
            await core_only.initialise_store.handle(
                InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
            )
        finally:
            await core_only.client.close()

    asyncio.run(init_core_only())
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("NOESIS_KNOWLEDGE_SPACE", "default")
    digest = graph_digest(neo4j_settings)

    code, envelope = run_json(capsys, ["review", "queue"])

    assert code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert error["metadata"] == {"missing_steps": ["review"]}
    assert "Run `noesis store init`." in error["next_steps"]
    assert graph_digest(neo4j_settings) == digest


async def test_uniqueness_constraints_ignore_nodes_without_the_property(
    review_env: ReviewNeo4jEnv,
) -> None:
    """The `live_key` design: many nodes may lack the property, none may share a value."""
    settings = review_env.settings
    query(settings, "CREATE (:Assertion {id: 'x1'}), (:Assertion {id: 'x2'}), (:Decision {seq: 1})")
    query(settings, "CREATE (:Decision {seq: 2})")

    assert query(settings, "MATCH (n) WHERE n.id IN ['x1', 'x2'] RETURN count(n) AS total") == [
        {"total": 2}
    ]


@pytest.mark.parametrize(
    ("label", "prop"), [("Assertion", "live_key"), ("Decision", "decision_key")]
)
async def test_a_second_node_with_the_same_key_violates_the_constraint(
    review_env: ReviewNeo4jEnv, label: str, prop: str
) -> None:
    settings = review_env.settings
    query(settings, f"CREATE (:{label} {{{prop}: 'same'}})")  # type: ignore[arg-type]

    with pytest.raises(ConstraintError) as raised:
        query(settings, f"CREATE (:{label} {{{prop}: 'same'}})")  # type: ignore[arg-type]

    assert raised.value.code == "Neo.ClientError.Schema.ConstraintValidationFailed"


async def test_removing_live_key_frees_the_value_in_the_same_transaction(
    review_env: ReviewNeo4jEnv,
) -> None:
    settings = review_env.settings
    query(settings, "CREATE (:Assertion {id: 'a1', live_key: 'k'})")

    with admin_driver(settings) as driver, driver.session(database=settings.database) as session:
        transaction = session.begin_transaction()
        transaction.run("MATCH (a:Assertion {id: 'a1'}) REMOVE a.live_key").consume()
        transaction.run("CREATE (:Assertion {id: 'a2', live_key: 'k'})").consume()
        transaction.commit()

    rows = query(settings, "MATCH (a:Assertion) RETURN a.id AS id, a.live_key AS live_key")
    assert sorted((row["id"], row["live_key"]) for row in rows) == [("a1", None), ("a2", "k")]
