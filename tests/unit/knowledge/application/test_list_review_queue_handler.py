"""ListReviewQueueHandler: what needs review, who may decide it (FR-014; AC-002, AC-014)."""

import pytest
from pydantic import ValidationError
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import USER
from tests.support.review_fakes import (
    ReviewEnv,
    make_review_env,
    seed_assertion,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import (
    ReviewQueueItemDto,
    ReviewQueuePageDto,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
)
from noesis.exceptions import SpaceNotFoundError, StoreNotInitialisedError

pytestmark = pytest.mark.unit


def queue(actor: Actor, **overrides: object) -> ListReviewQueueQuery:
    values: dict[str, object] = {"space_key": Key(value="default"), "actor": actor}
    return ListReviewQueueQuery(**{**values, **overrides})  # type: ignore[arg-type]


async def fixture(env: ReviewEnv) -> dict[str, RecordId]:
    """K_P (acme), K_Q (other), K_G (space-wide) and A_P (acme, one evidence) proposed; K_A accepted."""
    evidence = await seed_experience(env)
    k_p = await seed_knowledge(env, "kp", project="acme")
    k_q = await seed_knowledge(env, "kq", project="other")
    k_g = await seed_knowledge(env, "kg")
    k_a = await seed_knowledge(env, "ka", project="acme", status=RecordStatusEnum.ACCEPTED)
    a_p = await seed_assertion(
        env,
        AssertionPredicateEnum.SUPPORTS,
        evidence,
        k_a,
        project="acme",
        evidence=(evidence,),
    )
    return {"k_p": k_p, "k_q": k_q, "k_g": k_g, "k_a": k_a, "a_p": a_p}


def by_id(page: ReviewQueuePageDto) -> dict[str, ReviewQueueItemDto]:
    return {item.id: item for item in page.items}


async def test_agent_sees_what_it_may_decide_and_what_needs_the_user() -> None:
    """AC-014: project queue for an agent."""
    env = await make_review_env()
    r = await fixture(env)

    page = await env.list_review_queue.handle(queue(AGENT, project=Key(value="acme")))

    assert [i.id for i in page.items] == sorted([r["k_p"].value, r["a_p"].value, r["k_g"].value])
    items = by_id(page)
    for name in ("k_p", "a_p"):
        item = items[r[name].value]
        assert (item.requires, item.decidable_by_caller) == ("agent_or_user", True)
    k_g = items[r["k_g"].value]
    assert (k_g.requires, k_g.decidable_by_caller) == ("user", False)
    assert (items[r["a_p"].value].evidence_count, items[r["k_p"].value].evidence_count) == (1, None)
    assert items[r["k_p"].value].title
    assert (items[r["a_p"].value].predicate, items[r["a_p"].value].type) == (
        "supports",
        "assertion",
    )
    assert r["k_a"].value not in items
    assert r["k_q"].value not in items


async def test_the_user_may_decide_every_item_but_requirements_do_not_change() -> None:
    env = await make_review_env()
    r = await fixture(env)

    page = await env.list_review_queue.handle(queue(USER))

    items = by_id(page)
    assert set(items) == {r["k_p"].value, r["k_q"].value, r["k_g"].value, r["a_p"].value}
    assert all(i.decidable_by_caller for i in page.items)
    assert items[r["k_g"].value].requires == "user"
    assert items[r["k_q"].value].requires == "agent_or_user"


async def test_global_scope_lists_only_space_wide_items() -> None:
    env = await make_review_env()
    r = await fixture(env)

    page = await env.list_review_queue.handle(queue(AGENT, global_only=True))

    assert [i.id for i in page.items] == [r["k_g"].value]


async def test_type_and_predicate_filters_narrow_the_queue() -> None:
    env = await make_review_env()
    r = await fixture(env)

    only_assertions = await env.list_review_queue.handle(
        queue(AGENT, record_type=RecordTypeEnum.ASSERTION)
    )
    only_knowledge = await env.list_review_queue.handle(
        queue(AGENT, record_type=RecordTypeEnum.KNOWLEDGE)
    )

    assert [i.id for i in only_assertions.items] == [r["a_p"].value]
    assert r["a_p"].value not in {i.id for i in only_knowledge.items}


async def test_pages_follow_the_cursor_without_repeats() -> None:
    env = await make_review_env()
    r = await fixture(env)

    first = await env.list_review_queue.handle(queue(USER, limit=2))
    second = await env.list_review_queue.handle(queue(USER, limit=2, cursor=first.next_cursor))

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert [i.id for i in (*first.items, *second.items)] == sorted(
        [r["k_p"].value, r["k_q"].value, r["k_g"].value, r["a_p"].value]
    )


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_must_be_positive(limit: int) -> None:
    with pytest.raises(ValidationError):
        queue(USER, limit=limit)


async def test_an_unknown_space_is_reported() -> None:
    env = await make_review_env()

    with pytest.raises(SpaceNotFoundError):
        await env.list_review_queue.handle(queue(USER, space_key=Key(value="nowhere")))


async def test_the_review_schema_step_is_required() -> None:
    env = await make_review_env(steps=("core",))

    with pytest.raises(StoreNotInitialisedError):
        await env.list_review_queue.handle(queue(USER))
