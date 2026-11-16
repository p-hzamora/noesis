"""C4 writes append to C5a's change feed in their own transaction (AC-019, AC-031), over the pinned Neo4j."""

import pytest
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    accept_knowledge_command,
    bulk_command,
    retract_knowledge_command,
)
from tests.support.review_support import (
    MIGRATED,
    CommitFailingFactory,
    ReviewNeo4jEnv,
    count_nodes,
    decisions_of,
    stored_status,
)

from noesis.bounded_context.knowledge.domain.value_objects import AssertionPredicateEnum
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.exceptions import GraphStoreUnavailableError, ReviewNotAuthorisedError

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

Entry = tuple[str, str, str, int | None, str | None]


async def read_feed(env: ReviewNeo4jEnv, after: int = 0) -> list[tuple[int, Entry]]:
    """Feed entries with a sequence above `after`, read through C5a's change-feed reader."""
    changes = await Neo4jRecordChangeFeedAdapter(env.client).changes_after(
        after, space_id=await env.space_id(), limit=1000
    )
    return [
        (c.sequence, (c.change_kind, c.record_type, c.record_id, c.revision, c.status))
        for c in changes
    ]


async def head(env: ReviewNeo4jEnv) -> int:
    """The last sequence of the space (0 when empty)."""
    return max((sequence for sequence, _ in await read_feed(env)), default=0)


async def entries_since(env: ReviewNeo4jEnv, mark: int) -> list[Entry]:
    return [entry for _, entry in await read_feed(env, mark)]


async def test_ac019_change_feed_entries_neo4j(review_env: ReviewNeo4jEnv) -> None:
    subject = await review_env.seed_accepted("s")
    object_ = await review_env.seed_accepted("o")
    k = await review_env.capture("k")
    global_k = await review_env.capture("gk")
    n = await review_env.seed_accepted("n")
    old = await review_env.seed_accepted("old")
    mark = await head(review_env)

    a = await review_env.propose(AssertionPredicateEnum.SUPPORTS, subject, object_, "pa")
    assert await entries_since(review_env, mark) == [
        ("created", "assertion", a.value, None, "proposed")
    ]

    mark = await head(review_env)
    await review_env.accept_assertion().handle(accept_assertion_command(a, "aa", actor=USER))
    assert await entries_since(review_env, mark) == [
        ("status_changed", "assertion", a.value, None, "accepted")
    ]

    mark = await head(review_env)
    await review_env.accept_knowledge().handle(
        accept_knowledge_command(k, "ak", expected=1, actor=USER)
    )
    assert await entries_since(review_env, mark) == [
        ("status_changed", "knowledge", k.value, 1, "accepted")
    ]

    sup = await review_env.propose(AssertionPredicateEnum.SUPERSEDES, n, old, "ps")
    mark = await head(review_env)
    await review_env.accept_assertion().handle(accept_assertion_command(sup, "as", actor=USER))
    assert await entries_since(review_env, mark) == [
        ("status_changed", "assertion", sup.value, None, "accepted"),
        ("status_changed", "knowledge", old.value, 1, "superseded"),
    ]

    mark = await head(review_env)
    with pytest.raises(ReviewNotAuthorisedError):
        await review_env.accept_knowledge().handle(accept_knowledge_command(global_k, "refused"))
    await review_env.accept_knowledge().handle(
        accept_knowledge_command(global_k, "preview", actor=USER, apply=False)
    )
    replay = await review_env.accept_knowledge().handle(
        accept_knowledge_command(k, "ak", expected=1, actor=USER)
    )
    assert replay.replayed is True
    assert await entries_since(review_env, mark) == []


async def test_ac019_change_feed_retract_neo4j(review_env: ReviewNeo4jEnv) -> None:
    record = await review_env.seed_accepted("k")
    mark = await head(review_env)

    await review_env.retract_knowledge().handle(retract_knowledge_command(record, "r"))

    assert await entries_since(review_env, mark) == [
        ("status_changed", "knowledge", record.value, 1, "retracted")
    ]


async def test_ac019_change_feed_failed_commit_leaves_no_status_change_or_change_node_neo4j(
    review_env: ReviewNeo4jEnv,
) -> None:
    record = await review_env.capture("k", project="acme")
    mark = await head(review_env)
    changes_before = count_nodes(review_env.settings, "Change")
    factory = CommitFailingFactory(review_env.uow, fail_on=1)

    with pytest.raises(GraphStoreUnavailableError):
        await review_env.accept_knowledge(factory).handle(accept_knowledge_command(record, "ak"))

    assert stored_status(review_env.settings, record.value) == "proposed"
    assert decisions_of(review_env.settings, record.value) == []
    assert count_nodes(review_env.settings, "Change") == changes_before
    assert await entries_since(review_env, mark) == []


async def test_ac031_bulk_accept_change_feed(review_env: ReviewNeo4jEnv) -> None:
    fixture = await review_env.seed_bulk_fixture()
    mark = await head(review_env)

    await review_env.bulk_accept().handle(bulk_command(MIGRATED, apply=False))
    assert await entries_since(review_env, mark) == []

    await review_env.bulk_accept().handle(bulk_command(MIGRATED))
    assert await entries_since(review_env, mark) == [
        ("status_changed", "knowledge", fixture.k1.value, 2, "accepted"),
        ("status_changed", "knowledge", fixture.k2.value, 1, "accepted"),
    ]

    after_run = await head(review_env)
    await review_env.bulk_accept().handle(bulk_command(MIGRATED))
    assert await entries_since(review_env, after_run) == []


async def test_ac031_bulk_accept_change_feed_failed_commit_keeps_the_earlier_entry_neo4j(
    review_env: ReviewNeo4jEnv,
) -> None:
    fixture = await review_env.seed_bulk_fixture()
    mark = await head(review_env)
    factory = CommitFailingFactory(review_env.uow, fail_on=2)

    with pytest.raises(GraphStoreUnavailableError):
        await review_env.bulk_accept(factory).handle(bulk_command(MIGRATED))

    settings = review_env.settings
    assert stored_status(settings, fixture.k2.value) == "proposed"
    assert decisions_of(settings, fixture.k2.value) == []
    assert await entries_since(review_env, mark) == [
        ("status_changed", "knowledge", fixture.k1.value, 2, "accepted")
    ]
