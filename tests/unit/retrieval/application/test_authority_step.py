"""The authority step of the search pipeline (AC-023, FR-004)."""

from types import SimpleNamespace

import pytest
from tests.support.retrieval.retrieval_fakes import RetrievalWorld, make_request

from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher

pytestmark = pytest.mark.unit


def seed_statuses(world: RetrievalWorld) -> None:
    world.add_knowledge("K_A", status="accepted")
    world.add_knowledge("K_P", status="proposed")
    world.add_knowledge("K_S", status="superseded")
    world.add_knowledge("K_R", status="retracted")
    world.add_experience("E")


async def test_ac023_unwired() -> None:
    world = RetrievalWorld()
    seed_statuses(world)
    world.match("K_P", "K_S", "E", "K_A", "K_R")  # fused ranks 1..5

    result = await world.searcher().search(make_request(limit=10))

    assert [h.record_id for h in result.hits] == ["K_A", "E", "K_P", "K_S"]
    assert [h.authority.value for h in result.hits] == [
        "authoritative",
        "experience",
        "proposed",
        "superseded",
    ]
    assert [h.status for h in result.hits] == ["accepted", None, "proposed", "superseded"]


async def test_ac023_unwired_retracted_only_when_asked_for() -> None:
    world = RetrievalWorld()
    seed_statuses(world)
    world.match("K_P", "K_S", "E", "K_A", "K_R")

    result = await world.searcher().search(make_request(limit=10, statuses=["retracted"]))

    assert [h.record_id for h in result.hits] == ["K_R"]
    assert result.hits[0].authority.value == "retracted"


@pytest.mark.skip(reason="wired half runs once C8 adds the review-state port (Q-008)")
async def test_ac023_wired() -> None:
    world = RetrievalWorld()
    seed_statuses(world)
    world.add_knowledge("K_U", status="proposed")
    world.match("K_U", "K_S", "K_P", "E", "K_A", "K_R")  # fused ranks 1..6
    authorities = {
        "K_A": "authoritative",
        "K_P": "proposed",
        "K_S": "superseded",
        "K_R": "retracted",
        "E": "not_reviewable",
    }  # nothing for K_U

    class FakeReviewStateReader:
        async def get_states(self, record_ids: list[str], *, space_id: str) -> list[object]:
            return [
                SimpleNamespace(record_id=record_id, authority=authorities[record_id])
                for record_id in record_ids
                if record_id in authorities
            ]

    searcher = RecordSearcher(
        text_search=world.text_search,
        states=world.states,
        neighbours=world.neighbours,
        indexables=world.indexables,
        candidate_sources=(),
        cursors=world.cursors,
        feed=world.feed,
        review_states=FakeReviewStateReader(),  # type: ignore[call-arg]
    )

    result = await searcher.search(make_request(limit=10))

    assert [h.record_id for h in result.hits] == ["K_A", "E", "K_U", "K_P", "K_S"]
    assert [h.authority.value for h in result.hits] == [
        "authoritative",
        "experience",
        "unreviewed",
        "proposed",
        "superseded",
    ]
    assert result.hits[2].status == "proposed"  # the stored status, whatever the label
