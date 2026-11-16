"""C8 evidence admission, grounding, fail-closed prerequisites and tools."""

from unittest.mock import AsyncMock

import pytest
from tests.support.retrieval.retrieval_fakes import RetrievalWorld, make_request

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import (
    BriefingDraftDto,
    BriefingItemDto,
    CitationDto,
    RecallRequestDto,
)
from noesis.bounded_context.retrieval.application.handlers.queries.recall_handler import (
    RecallHandler,
)
from noesis.bounded_context.retrieval.application.services.briefing_redactor import BriefingRedactor
from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    CatalogAvailabilityEntryContract,
    CatalogAvailabilityResultContract,
    CatalogAvailabilityRuntimeContract,
    GraphNeighbourContract,
    RecordReviewStateContract,
)

pytestmark = pytest.mark.unit
CAT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def setup_recall(
    *, budget: int = 24000, review: bool = True
) -> tuple[RecallHandler, RetrievalWorld, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    world = RetrievalWorld()
    world.add_knowledge("A", status="accepted", body="Use ports")
    world.add_knowledge("P", status="proposed", body="password=supersecret123")
    world.add_knowledge("O", status="superseded", body="Old guidance")
    world.add_experience("E", body="A run outcome")
    world.match("P", "A", "E", "O")
    states = [
        RecordReviewStateContract(
            record_id=key,
            record_type="knowledge" if key != "E" else "experience",
            authority=authority,
            status=status,
            effective_status=status,
            head_revision=1 if key != "E" else None,
            tags=["origin:migrated"] if key == "P" else [],
            superseded_by_record_ids=["A"] if key == "O" else [],
        )
        for key, authority, status in [
            ("A", "authoritative", "accepted"),
            ("P", "proposed", "proposed"),
            ("O", "superseded", "superseded"),
            ("E", "not_reviewable", None),
        ]
    ]
    reviews = AsyncMock()
    reviews.get_states.return_value = states
    recommendations = AsyncMock()
    recommendations.by_subjects.return_value = []
    model = AsyncMock()
    model.synthesize.return_value = BriefingDraftDto()
    catalog = AsyncMock()
    handler = RecallHandler(
        world.searcher(),
        world.indexables,
        reviews=reviews if review else None,
        recommendations=recommendations,
        catalog=catalog,
        model=model,
        redactor=BriefingRedactor(),
        max_evidence_chars=budget,
    )
    return handler, world, reviews, recommendations, catalog, model


def request(*, digest: bool = True) -> RecallRequestDto:
    return RecallRequestDto(
        search=make_request(), no_synthesis=digest, runtimes=("claude-code", "codex")
    )


async def test_digest_orders_labels_redacts_and_never_calls_model() -> None:
    handler, _, _, _, catalog, model = setup_recall()
    result = await handler.handle(request())
    assert [record.id for record in result.records] == ["A", "E", "P", "O"]
    assert result.synthesis == "digest"
    assert result.search.semantic_state.value == "absent"
    assert "supersecret" not in result.model_dump_json()
    assert result.records[-1].superseded_by == ("A",)
    assert result.next_steps == ("noesis review accept --tag origin:migrated --all --yes",)
    assert result.constraints[0].citations == (CitationDto(record_id="A", revision=1),)
    assert len(result.unconfirmed) == 2
    model.synthesize.assert_not_called()
    catalog.check.assert_not_called()


async def test_grounding_mixed_proposals_fabrications_wrong_revisions_and_no_citations() -> None:
    handler, _, _, _, _, model = setup_recall()

    def item(text: str, *pairs: tuple[str, int | None]) -> BriefingItemDto:
        return BriefingItemDto(
            text=text,
            citations=tuple(CitationDto(record_id=key, revision=rev) for key, rev in pairs),
        )

    model.synthesize.return_value = BriefingDraftDto(
        constraints=(
            item("accepted", ("A", 1)),
            item("proposal", ("P", 1)),
            item("mixed", ("A", 1), ("P", 1)),
            item("invented", ("fake", 1)),
            item("wrong revision", ("A", 2)),
            item("unsupported"),
        ),
        context=(item("experience", ("E", None)),),
    )
    result = await handler.handle(request(digest=False))
    assert [item.text for item in result.constraints] == ["accepted"]
    assert [item.text for item in result.unconfirmed] == ["proposal", "mixed"]
    assert len(result.unsupported) == 3
    assert result.tools == ()
    assert "supersecret" not in str(model.synthesize.call_args)


async def test_budget_omits_whole_bodies_and_still_suggests_migration_review() -> None:
    handler, _, _, _, _, model = setup_recall(budget=1)
    result = await handler.handle(request(digest=False))
    assert result.synthesis == "no_evidence"
    assert all(not record.read and record.omitted_reason == "budget" for record in result.records)
    assert result.next_steps
    model.synthesize.assert_not_called()


async def test_second_head_change_omits_evidence() -> None:
    handler, _, reviews, _, _, _ = setup_recall()
    states = reviews.get_states.return_value
    reviews.get_states.side_effect = [
        states,
        [state.model_copy(update={"head_revision": 2}) for state in states],
    ]
    result = await handler.handle(request())
    assert result.synthesis == "no_evidence"
    assert all(record.omitted_reason == "review_changed" for record in result.records)


async def test_missing_review_never_makes_authoritative_guidance() -> None:
    handler, _, _, _, _, _ = setup_recall(review=False)
    result = await handler.handle(request())
    assert result.constraints == ()
    assert result.capabilities["review"] == "not_available"
    assert len(result.unconfirmed) == 3


@pytest.mark.parametrize("stage", ["review", "body", "availability"])
async def test_store_failure_propagates_without_model(stage: str) -> None:
    handler, world, reviews, recommendations, catalog, model = setup_recall()
    error = GraphStoreUnavailableError("offline")
    if stage == "review":
        reviews.get_states.side_effect = error
    elif stage == "body":
        world.indexables.get = AsyncMock(side_effect=error)
    else:
        recommendations.by_subjects.return_value = [endorsement("good")]
        catalog.check.side_effect = error
    with pytest.raises(GraphStoreUnavailableError):
        await handler.handle(request(digest=False))
    model.synthesize.assert_not_called()


def endorsement(identifier: str, **overrides: object) -> AssertionSummaryContract:
    return AssertionSummaryContract(
        assertion_id=identifier,
        predicate="recommends",
        subject_id="A",
        subject_at_revision=1,
        object_id=CAT,
        object_type="catalog_entry",
        status="accepted",
    ).model_copy(update=overrides)


async def test_scoped_live_endorsements_and_each_runtime_observation_survive() -> None:
    handler, _, _, recommendations, catalog, _ = setup_recall()
    recommendations.by_subjects.return_value = [
        endorsement("accepted"),
        endorsement("proposed", status="proposed"),
        endorsement("stale", subject_at_revision=2),
        endorsement("foreign", project_key="other"),
        endorsement("dead", status="retracted"),
    ]
    catalog.check.return_value = CatalogAvailabilityResultContract(
        outcome="checked",
        runtimes=tuple(
            CatalogAvailabilityRuntimeContract(
                runtime=runtime,
                host="test",
                observed_at="now",
                entries=(
                    CatalogAvailabilityEntryContract(
                        entry_id=CAT,
                        kind="skill",
                        name="ddd",
                        purpose="design",
                        location="hint",
                        status=status,
                        reason=reason,
                    ),
                ),
            )
            for runtime, status, reason in [
                ("claude-code", "unavailable", "not_installed"),
                ("codex", "available", "none"),
            ]
        ),
    )
    result = await handler.handle(request())
    (tool,) = result.tools
    assert tool.usable and tool.endorsement == "accepted"
    assert tool.assertion_ids == ("accepted", "proposed")
    assert len(tool.runtimes) == 2
    assert any("stale" in warning for warning in result.warnings)


async def test_not_checked_has_no_invented_tool_details() -> None:
    handler, _, _, recommendations, catalog, _ = setup_recall()
    recommendations.by_subjects.return_value = [endorsement("accepted")]
    catalog.check.return_value = CatalogAvailabilityResultContract(
        outcome="not_checked", reason_code="runtime_unresolved"
    )
    result = await handler.handle(request())
    assert result.tools == () and result.tools_state == "not_verified"
    assert any("runtime_unresolved" in warning for warning in result.warnings)


@pytest.mark.parametrize("change", ["retracted", "foreign", "missing"])
async def test_recheck_drops_hidden_records_instead_of_leaking_old_metadata(change: str) -> None:
    handler, _, reviews, _, _, _ = setup_recall()
    states = reviews.get_states.return_value
    final = (
        []
        if change == "missing"
        else [
            state.model_copy(
                update={"status": "retracted", "authority": "retracted"}
                if change == "retracted"
                else {"project_key": "foreign"}
            )
            for state in states
        ]
    )
    reviews.get_states.side_effect = [states, final]
    result = await handler.handle(request())
    assert result.records == () and result.synthesis == "no_evidence"


async def test_first_head_refresh_reads_new_exact_revision_once() -> None:
    handler, world, reviews, _, _, _ = setup_recall()
    world.match("A")
    states = [
        state.model_copy(update={"head_revision": 2})
        for state in reviews.get_states.return_value
        if state.record_id == "A"
    ]
    reviews.get_states.return_value = states
    world.add_knowledge("A", revision=2, status="accepted", body="refreshed")
    result = await handler.handle(request())
    assert result.records[0].revision == 2
    assert result.records[0].body == "refreshed"
    assert world.indexables.gets == [("A", 2)]


async def test_missing_catalog_capability_and_empty_search_skip_model() -> None:
    handler, world, _, _, _, model = setup_recall()
    handler._catalog = None
    result = await handler.handle(request())
    assert result.tools == () and result.capabilities["catalog"] == "not_available"
    world.match()
    result = await handler.handle(request(digest=False))
    assert result.synthesis == "no_evidence" and result.records == ()
    model.synthesize.assert_not_called()


async def test_changed_head_with_retraction_is_hidden_before_revision_omission() -> None:
    handler, world, _, _, _, _ = setup_recall()
    original = world.indexables.get

    async def changed(record_id: str, revision: int | None, *, space_id: str):
        body = await original(record_id, revision, space_id=space_id)
        return body.model_copy(update={"head_revision": 2, "status": "retracted"})

    world.indexables.get = changed
    result = await handler.handle(request())
    assert result.records == ()


async def test_recheck_runs_after_tool_gathering_and_before_the_model() -> None:
    handler, _, reviews, recommendations, _, model = setup_recall()
    states = reviews.get_states.return_value
    calls: list[str] = []

    async def get_states(ids: list[str], *, space_id: str) -> list[RecordReviewStateContract]:
        calls.append("states")
        if calls.count("states") < 2:
            return states
        return [state.model_copy(update={"head_revision": 2}) for state in states]

    async def by_subjects(ids: list[str], *, space_id: str) -> list[AssertionSummaryContract]:
        calls.append("tools")
        return []

    reviews.get_states.side_effect = get_states
    recommendations.by_subjects.side_effect = by_subjects
    result = await handler.handle(request(digest=False))
    assert calls == ["states", "tools", "states"]
    assert result.synthesis == "no_evidence"
    model.synthesize.assert_not_called()
    assert all(record.omitted_reason == "review_changed" for record in result.records)


def test_discovery_ids_and_labels_are_redacted() -> None:
    handler, *_ = setup_recall()
    secret = "ghp_" + "a" * 24
    path = GraphNeighbourContract(
        record_id=secret,
        seed_id=secret,
        relation="links_to",
        shared_sources=0,
        original_target_id=secret,
        origin=secret,
        anchors=(secret,),
        supersession_path=(secret,),
        warnings=(secret,),
    )
    masked = handler._mask_path(path)
    assert secret not in masked.model_dump_json()
