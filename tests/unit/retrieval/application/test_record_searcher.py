"""RecordSearcher, the single search pipeline (D-017), with fakes of every port."""

import pytest
from tests.support.retrieval.retrieval_fakes import (
    OTHER_SPACE,
    SPACE,
    T1,
    RetrievalWorld,
    make_request,
)

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchHitDto,
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.application.handlers.queries.find_similar_records_handler import (
    FindSimilarRecordsHandler,
    FindSimilarRecordsQuery,
)
from noesis.bounded_context.retrieval.application.handlers.queries.search_records_handler import (
    SearchRecordsHandler,
)
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.domain.enums import (
    AuthorityTierEnum,
    CandidateKindEnum,
    ProjectScopeEnum,
)
from noesis.bounded_context.retrieval.domain.value_objects.projection_key import ProjectionKey
from noesis.exceptions import IndexRebuildRequiredError

pytestmark = pytest.mark.unit

ACME: str = "P-acme"
OTHER: str = "P-other"


def ids(result: RecordSearchResultDto) -> list[str]:
    return [hit.record_id for hit in result.hits]


def kinds(hit: RecordSearchHitDto) -> tuple[str, ...]:
    return tuple(str(kind.value) for kind in hit.sources)


def world_with_projects() -> RetrievalWorld:
    world = RetrievalWorld()
    world.states.add_project(SPACE, "acme", ACME)
    world.states.add_project(SPACE, "other", OTHER)
    return world


async def test_hit_has_exactly_the_eleven_fields() -> None:
    assert set(RecordSearchHitDto.model_fields) == {
        "record_id",
        "record_type",
        "subtype",
        "title",
        "revision",
        "status",
        "authority",
        "project_id",
        "sources",
        "revised_at",
        "rank",
        "discovery",
        "warnings",
    }


async def test_ac001_accepted_outranks_proposed_and_hits_carry_stored_status() -> None:
    world = world_with_projects()
    world.add_knowledge("K-P", status="proposed")
    world.add_knowledge("K-A", status="accepted")
    world.add_experience("E")
    world.match("K-P", "E", "K-A")

    result = await world.searcher().search(make_request())

    assert ids(result) == ["K-A", "E", "K-P"]
    assert [h.rank for h in result.hits] == [1, 2, 3]
    by_id = {h.record_id: h for h in result.hits}
    assert by_id["K-A"].authority == AuthorityTierEnum("authoritative")
    assert by_id["K-A"].status == "accepted"
    assert by_id["K-P"].authority == AuthorityTierEnum("proposed")
    assert by_id["K-P"].status == "proposed"


async def test_experience_hit_has_null_title_revision_and_status() -> None:
    world = world_with_projects()
    world.add_experience("E")
    world.match("E")

    (hit,) = (await world.searcher().search(make_request())).hits

    assert (hit.record_type, hit.title, hit.revision, hit.status) == (
        "experience",
        None,
        None,
        None,
    )
    assert hit.authority == AuthorityTierEnum("experience")
    assert hit.revised_at == T1
    assert kinds(hit) == ("lexical",)


async def test_ac002_semantic_hit_at_an_old_revision_is_dropped_and_counted() -> None:
    world = world_with_projects()
    world.add_knowledge("K", revision=2)
    world.add_knowledge("K2", revision=2)
    world.match("K")
    world.semantic.set_hits(
        SPACE, [ProjectionKey(record_id="K", revision=1), ProjectionKey(record_id="K2", revision=1)]
    )
    world.cursors.set("semantic", SPACE, 0)

    result = await world.searcher(with_semantic=True).search(make_request())

    assert ids(result) == ["K"]
    assert kinds(result.hits[0]) == ("lexical",)
    assert result.stale_hits == 2


async def test_semantic_hit_at_the_head_revision_is_served_with_its_source() -> None:
    world = world_with_projects()
    world.add_knowledge("K", revision=2)
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id="K", revision=2)])
    world.cursors.set("semantic", SPACE, 0)

    result = await world.searcher(with_semantic=True).search(make_request())

    assert ids(result) == ["K"]
    assert kinds(result.hits[0]) == ("semantic",)
    assert result.stale_hits == 0


async def test_experience_hit_with_null_revision_is_current_not_stale() -> None:
    world = world_with_projects()
    world.add_experience("E")
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id="E", revision=None)])
    world.cursors.set("semantic", SPACE, 0)

    result = await world.searcher(with_semantic=True).search(make_request())

    assert ids(result) == ["E"]
    assert result.stale_hits == 0


async def test_ac003_project_scope_returns_that_project_plus_space_wide_records() -> None:
    world = world_with_projects()
    world.add_knowledge("Ka", project_id=ACME)
    world.add_knowledge("Ko", project_id=OTHER)
    world.add_knowledge("Kg", project_id=None)
    world.match("Ka", "Ko", "Kg")

    result = await world.searcher().search(make_request(project_key="acme"))

    assert sorted(ids(result)) == ["Ka", "Kg"]
    assert result.project_scope == ProjectScopeEnum("project")
    assert result.project_id == ACME


async def test_ac003_all_projects_applies_no_project_filter() -> None:
    world = world_with_projects()
    world.add_knowledge("Ka", project_id=ACME)
    world.add_knowledge("Ko", project_id=OTHER)
    world.add_knowledge("Kg", project_id=None)
    world.match("Ka", "Ko", "Kg")

    result = await world.searcher().search(make_request(project_key="acme", all_projects=True))

    assert sorted(ids(result)) == ["Ka", "Kg", "Ko"]
    assert result.project_scope == ProjectScopeEnum("all_projects")
    assert result.project_id is None


@pytest.mark.parametrize("project_key", [None, "zeta"])
async def test_ac003_no_resolvable_project_searches_space_wide_records_only(
    project_key: str | None,
) -> None:
    world = world_with_projects()
    world.add_knowledge("Ka", project_id=ACME)
    world.add_knowledge("Kg", project_id=None)
    world.match("Ka", "Kg")

    result = await world.searcher().search(make_request(project_key=project_key))

    assert ids(result) == ["Kg"]
    assert result.project_scope == ProjectScopeEnum("space_wide_only")
    assert result.project_id is None


async def test_records_of_another_space_are_never_returned() -> None:
    world = world_with_projects()
    world.add_knowledge("Ks")
    world.add_knowledge("Kt", space_id=OTHER_SPACE)
    world.match("Ks", "Kt")  # the text index of S wrongly lists Kt: the state reader omits it

    result = await world.searcher().search(make_request())

    assert ids(result) == ["Ks"]


async def test_statuses_default_excludes_retracted_and_can_be_asked_for() -> None:
    world = world_with_projects()
    world.add_knowledge("K-A", status="accepted")
    world.add_knowledge("K-R", status="retracted")
    world.match("K-A", "K-R")

    default = await world.searcher().search(make_request())
    asked = await world.searcher().search(make_request(statuses=["retracted"]))

    assert ids(default) == ["K-A"]
    assert ids(asked) == ["K-R"]
    assert asked.hits[0].authority == AuthorityTierEnum("retracted")


async def test_tag_type_and_status_filters_narrow_the_hits() -> None:
    world = world_with_projects()
    world.add_knowledge("K-tag", tags=["layout"], status="accepted")
    world.add_knowledge("K-plain", status="accepted")
    world.add_experience("E")
    world.match("K-tag", "K-plain", "E")

    by_tag = await world.searcher().search(make_request(tags=["layout"]))
    by_type = await world.searcher().search(make_request(record_types=["experience"]))
    by_status = await world.searcher().search(make_request(statuses=["accepted"]))

    assert ids(by_tag) == ["K-tag"]
    assert ids(by_type) == ["E"]
    assert sorted(ids(by_status)) == ["K-plain", "K-tag"]


async def test_limit_caps_the_returned_hits() -> None:
    world = world_with_projects()
    for number in range(1, 7):
        world.add_knowledge(f"K{number}")
    world.match(*(f"K{number}" for number in range(1, 7)))

    result = await world.searcher().search(make_request(limit=4))

    assert ids(result) == ["K1", "K2", "K3", "K4"]
    assert result.filter_shortfall is False


def seed_filtered_corpus(world: RetrievalWorld, *, acme_matches: int) -> None:
    """Twenty matching records: R01..R06 in another project, then `acme_matches` in acme."""
    ordered: list[str] = []
    for number in range(1, 21):
        record_id = f"R{number:02d}"
        in_acme = 7 <= number < 7 + acme_matches
        world.add_knowledge(record_id, project_id=ACME if in_acme else OTHER)
        ordered.append(record_id)
    world.match(*ordered)


async def test_ac014_filter_leaving_too_few_retries_once_with_ten_times_the_limit() -> None:
    world = world_with_projects()
    seed_filtered_corpus(world, acme_matches=2)

    result = await world.searcher().search(make_request(project_key="acme", limit=2))

    assert world.text_search.limits == [6, 20]
    assert ids(result) == ["R07", "R08"]
    assert result.filter_shortfall is False


async def test_ac014_still_short_after_the_retry_sets_filter_shortfall() -> None:
    world = world_with_projects()
    seed_filtered_corpus(world, acme_matches=1)

    result = await world.searcher().search(make_request(project_key="acme", limit=2))

    assert world.text_search.limits == [6, 20]  # one retry, no more
    assert ids(result) == ["R07"]
    assert result.filter_shortfall is True


async def test_no_retry_when_the_first_collection_fills_the_limit() -> None:
    world = world_with_projects()
    seed_filtered_corpus(world, acme_matches=0)
    for number in range(1, 7):
        world.add_knowledge(f"R{number:02d}", project_id=ACME)  # the first collection suffices

    result = await world.searcher().search(make_request(project_key="acme", limit=2))

    assert world.text_search.limits == [6]
    assert len(result.hits) == 2
    assert result.filter_shortfall is False


async def test_q014_the_retry_is_capped_at_200_and_every_source_is_asked_the_same() -> None:
    world = world_with_projects()
    world.cursors.set("semantic", SPACE, 0)

    result = await world.searcher(with_semantic=True).search(make_request(limit=50))

    assert world.text_search.limits == [150, 200]
    assert world.semantic.limits == [150, 200]
    assert result.filter_shortfall is True


async def test_ac017_similar_excludes_the_anchor_and_keeps_every_status_and_project() -> None:
    world = world_with_projects()
    world.add_knowledge("A", status="accepted", project_id=ACME, title="hexagonal ports adapters")
    world.add_knowledge("B", status="retracted", project_id=OTHER)
    world.add_knowledge("C", status="superseded")
    world.add_knowledge("D", status="proposed", project_id=ACME)
    world.text_search.set_hits(SPACE, ["A", "B", "C", "D"], text="hexagonal ports adapters")

    result = await world.searcher().similar("A", space_id=SPACE, limit=10)

    assert ids(result) == ["B", "C", "D"]  # fused order, not reordered by authority
    assert [h.rank for h in result.hits] == [1, 2, 3]
    assert [h.authority.value for h in result.hits] == ["retracted", "superseded", "proposed"]
    assert all("lexical" in kinds(h) for h in result.hits)
    assert world.text_search.limits == [30]  # no over-fetch retry: there is no filter


async def test_similar_to_an_experience_queries_with_the_first_200_characters_of_its_body() -> None:
    world = world_with_projects()
    world.add_experience("E", body="x" * 300)
    world.add_knowledge("K")
    world.text_search.set_hits(SPACE, ["K"], text="x" * 200)

    result = await world.searcher().similar("E", space_id=SPACE, limit=5)

    assert world.text_search.calls[0].text == "x" * 200
    assert ids(result) == ["K"]


async def test_similar_uses_the_anchor_as_a_graph_seed() -> None:
    world = world_with_projects()
    world.add_knowledge("A", title="anchor title")
    world.add_knowledge("N")
    world.neighbours.add(SPACE, "N", seed_id="A")

    result = await world.searcher().similar("A", space_id=SPACE, limit=5)

    assert ids(result) == ["N"]
    assert kinds(result.hits[0]) == ("graph",)


async def test_similar_anchor_from_another_space_gives_no_hits() -> None:
    world = world_with_projects()
    world.add_knowledge("Kt", space_id=OTHER_SPACE, title="ports")
    world.add_knowledge("Ks", title="ports")
    world.text_search.set_hits(SPACE, ["Ks"])

    result = await world.searcher().similar("Kt", space_id=SPACE, limit=5)

    assert result.hits == ()


async def test_ac018_handler_delegates() -> None:
    world = world_with_projects()
    for number in range(1, 7):
        world.add_knowledge(
            f"K{number}", project_id=ACME if number % 2 else None, status="accepted"
        )
    world.match(*(f"K{number}" for number in range(1, 7)))
    searcher = world.searcher()
    request = make_request("ports", project_key="acme", limit=5)

    via_handler = await SearchRecordsHandler(searcher=searcher).handle(request)
    direct = await searcher.search(request)

    assert via_handler == direct
    assert len(direct.hits) == 5


async def test_find_similar_handler_delegates() -> None:
    world = world_with_projects()
    world.add_knowledge("A", title="ports")
    world.add_knowledge("B")
    world.text_search.set_hits(SPACE, ["A", "B"], text="ports")
    searcher = world.searcher()

    via_handler = await FindSimilarRecordsHandler(searcher=searcher).handle(
        FindSimilarRecordsQuery(record_id="A", space_id=SPACE, limit=5)
    )

    assert via_handler == await searcher.similar("A", space_id=SPACE, limit=5)
    assert ids(via_handler) == ["B"]


def graph_world() -> RetrievalWorld:
    world = world_with_projects()
    world.add_knowledge("S1")
    world.add_knowledge("S2")
    world.match("S1", "S2")
    return world


def only_graph(result: RecordSearchResultDto) -> list[str]:
    return [h.record_id for h in result.hits if kinds(h) == ("graph",)]


async def test_q013_graph_neighbours_ordered_by_shared_sources_then_seed_rank() -> None:
    world = graph_world()
    for record_id in ("N1", "N2", "N3", "Nx"):
        world.add_knowledge(record_id)
    # the fake returns pairs unordered; the searcher orders them
    world.neighbours.add(SPACE, "N3", seed_id="S2", shared_sources=1)
    world.neighbours.add(SPACE, "N2", seed_id="S1", shared_sources=1)
    world.neighbours.add(SPACE, "N1", seed_id="S1", shared_sources=2)

    result = await world.searcher().search(make_request(limit=10))

    assert only_graph(result) == ["N1", "N2", "N3"]
    assert "Nx" not in ids(result)
    assert {"S1", "S2"} <= set(ids(result))
    assert all(kinds(h) == ("lexical",) for h in result.hits if h.record_id.startswith("S"))


async def test_q013_equal_counts_and_seed_ranks_are_ordered_by_record_id() -> None:
    world = graph_world()
    for record_id in ("N-a", "N-b"):
        world.add_knowledge(record_id)
    world.neighbours.add(SPACE, "N-b", seed_id="S1")
    world.neighbours.add(SPACE, "N-a", seed_id="S1")

    result = await world.searcher().search(make_request(limit=10))

    assert only_graph(result) == ["N-a", "N-b"]


async def test_q013_shared_sources_are_counted_across_all_the_seeds_a_neighbour_touches() -> None:
    world = graph_world()
    for record_id in ("Nsum", "Nsingle", "Nlate"):
        world.add_knowledge(record_id)
    world.neighbours.add(SPACE, "Nsingle", seed_id="S1", shared_sources=1)
    world.neighbours.add(SPACE, "Nlate", seed_id="S2", shared_sources=2)
    world.neighbours.add(SPACE, "Nsum", seed_id="S1", shared_sources=1)
    world.neighbours.add(SPACE, "Nsum", seed_id="S2", shared_sources=1)

    result = await world.searcher().search(make_request(limit=10))

    # Nsum and Nlate share 2 Sources; Nsum touches the better seed (S1); Nsingle has 1
    assert only_graph(result) == ["Nsum", "Nlate", "Nsingle"]


async def test_q013_only_the_top_five_fused_records_are_seeds() -> None:
    world = world_with_projects()
    for number in range(1, 8):
        world.add_knowledge(f"R{number}")
    world.match(*(f"R{number}" for number in range(1, 8)))

    await world.searcher().search(make_request(limit=5))

    assert [tuple(call[0]) for call in world.neighbours.calls] == [("R1", "R2", "R3", "R4", "R5")]


async def test_q013_a_record_found_by_every_source_lists_them_in_fixed_order() -> None:
    world = world_with_projects()
    seeds = [f"S{number}" for number in range(1, 6)]
    for record_id in (*seeds, "M"):
        world.add_knowledge(record_id)
    world.match(*seeds, "M")
    world.semantic.set_hits(SPACE, [ProjectionKey(record_id=r, revision=1) for r in (*seeds, "M")])
    world.cursors.set("semantic", SPACE, 0)
    world.neighbours.add(SPACE, "M", seed_id="S1")  # M ranks 6th, so it is not a seed itself

    result = await world.searcher(with_semantic=True).search(make_request(limit=10))

    hit = next(h for h in result.hits if h.record_id == "M")
    assert hit.sources == (
        CandidateKindEnum("lexical"),
        CandidateKindEnum("graph"),
        CandidateKindEnum("semantic"),
    )


async def test_q013_neighbours_outside_the_project_scope_are_filtered() -> None:
    world = graph_world()
    world.add_knowledge("Nother", project_id=OTHER)
    world.neighbours.add(SPACE, "Nother", seed_id="S1")

    result = await world.searcher().search(make_request(project_key="acme", limit=10))

    assert "Nother" not in ids(result)


async def test_ac013_semantic_profile_differing_from_the_configured_one_needs_a_rebuild() -> None:
    world = world_with_projects()
    world.add_knowledge("K")
    world.match("K")
    world.semantic.set_profile({"model": "m2", "dimensions": 8})
    searcher = world.searcher(
        with_semantic=True, configured_profiles={"semantic": {"model": "m1", "dimensions": 8}}
    )

    with pytest.raises(IndexRebuildRequiredError):
        await searcher.search(make_request())


async def test_ac013_matching_or_unconfigured_profile_is_not_an_error() -> None:
    world = world_with_projects()
    world.add_knowledge("K")
    world.match("K")
    world.cursors.set("semantic", SPACE, 0)
    world.semantic.set_profile({"model": "m1"})

    matching = world.searcher(with_semantic=True, configured_profiles={"semantic": {"model": "m1"}})
    unconfigured = world.searcher(with_semantic=True)

    assert ids(await matching.search(make_request())) == ["K"]
    assert ids(await unconfigured.search(make_request())) == ["K"]


def searcher_over_projections(world: RetrievalWorld, *kinds: str) -> RecordSearcher:
    return RecordSearcher(
        text_search=world.text_search,
        states=world.states,
        neighbours=world.neighbours,
        indexables=world.indexables,
        candidate_sources=(),
        cursors=world.cursors,
        feed=world.feed,
        projection_kinds=kinds,
    )


async def test_pending_changes_is_the_largest_lag_over_every_registered_projection() -> None:
    world = world_with_projects()
    for record_id in ("A", "B", "C", "D", "E"):
        world.add_knowledge(record_id)
        world.feed.add(SPACE, record_id)
    world.cursors.set("probe", SPACE, 4)
    world.cursors.set("other", SPACE, 1)

    result = await searcher_over_projections(world, "probe", "other").search(make_request())

    assert result.pending_changes == 4


async def test_a_registered_projection_without_a_cursor_contributes_nothing() -> None:
    world = world_with_projects()
    world.add_knowledge("A")
    world.feed.add(SPACE, "A")

    result = await searcher_over_projections(world, "probe").search(make_request())

    assert result.pending_changes == 0
