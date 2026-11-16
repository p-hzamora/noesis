"""Semantic state and its degradation (FR-011; AC-012, AC-026)."""

import pytest
from tests.support.retrieval.retrieval_fakes import SPACE, RetrievalWorld, make_request

from noesis.bounded_context.retrieval.domain.enums import SemanticStateEnum
from noesis.bounded_context.retrieval.domain.value_objects.projection_key import ProjectionKey
from noesis.exceptions import SemanticIndexUnavailableError

pytestmark = pytest.mark.unit

HEAD: int = 5


def semantic_world(*, cursor: int | None) -> RetrievalWorld:
    """Feed head `HEAD`; the semantic source answers `K`; its cursor as given (None: never set)."""
    world = RetrievalWorld()
    world.add_knowledge("K")
    world.add_knowledge("L")
    for _ in range(HEAD):
        world.feed.add(SPACE, "K")
    world.match("L")
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id="K", revision=1)])
    if cursor is not None:
        world.cursors.set("semantic", SPACE, cursor)
    return world


@pytest.mark.parametrize(
    ("cursor", "state", "pending"),
    [(HEAD, "ready", 0), (HEAD - 3, "lagging", 3)],
)
async def test_ac026(cursor: int, state: str, pending: int) -> None:
    world = semantic_world(cursor=cursor)

    result = await world.searcher(with_semantic=True).search(
        make_request(require_semantic=True)
    )  # ready and lagging are both answered normally, even when semantic is required

    assert result.semantic_state == SemanticStateEnum(state)
    assert result.pending_changes == pending
    by_id = {h.record_id: h for h in result.hits}
    assert [k.value for k in by_id["K"].sources] == ["semantic"]
    assert [k.value for k in by_id["L"].sources] == ["lexical"]


async def test_ac026_cursor_never_initialised_is_unavailable() -> None:
    world = semantic_world(cursor=None)

    result = await world.searcher(with_semantic=True).search(make_request())

    assert result.semantic_state == SemanticStateEnum("unavailable")
    assert [h.record_id for h in result.hits] == ["L"]  # the other sources answer


async def test_no_registered_source_reports_absent_and_no_pending_changes() -> None:
    world = semantic_world(cursor=None)

    result = await world.searcher(with_semantic=False).search(make_request())

    assert result.semantic_state == SemanticStateEnum("absent")
    assert result.pending_changes == 0
    assert [h.record_id for h in result.hits] == ["L"]


async def test_ac012_source_down_answers_from_lexical_and_graph_and_says_unavailable() -> None:
    world = semantic_world(cursor=HEAD)
    world.add_knowledge("N")
    world.neighbours.add(SPACE, "N", seed_id="L")
    world.semantic.go_down()

    result = await world.searcher(with_semantic=True).search(make_request())

    assert result.semantic_state == SemanticStateEnum("unavailable")
    assert sorted(h.record_id for h in result.hits) == ["L", "N"]
    assert all("semantic" not in [k.value for k in h.sources] for h in result.hits)


@pytest.mark.parametrize("registered", [False, True])
async def test_ac012_require_semantic_fails_when_absent_or_unavailable(registered: bool) -> None:
    world = semantic_world(cursor=HEAD)
    world.semantic.go_down()

    with pytest.raises(SemanticIndexUnavailableError):
        await world.searcher(with_semantic=registered).search(make_request(require_semantic=True))


async def test_require_semantic_fails_when_the_cursor_was_never_initialised() -> None:
    world = semantic_world(cursor=None)

    with pytest.raises(SemanticIndexUnavailableError):
        await world.searcher(with_semantic=True).search(make_request(require_semantic=True))
