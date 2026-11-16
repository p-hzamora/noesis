"""`consolidation scan` over the pinned Neo4j with a stub similarity lookup (AC-05, AC-06)."""

import pytest
from tests.support.consolidation_support import MIGRATED, ConsolidationEnv
from tests.support.review_support import graph_digest

from noesis.bounded_context.knowledge.application.handlers.queries.scan_consolidation_candidates_handler import (
    ScanConsolidationCandidatesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    DismissalReasonKindEnum,
    Key,
    RecordId,
)
from noesis.exceptions import (
    GraphStoreUnavailableError,
    IndexRebuildRequiredError,
    IneligibleConsolidationMemberError,
    InvalidConsolidationError,
    RecordNotFoundError,
    SimilarityUnavailableError,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

KEY = Key(value="default")


def _scan(**fields: object) -> ScanConsolidationCandidatesQuery:
    return ScanConsolidationCandidatesQuery(space_key=KEY, **fields)  # type: ignore[arg-type]


async def test_ac05_a_record_scan_ranks_and_filters_without_any_score(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    anchor = await env.seed("a")
    near = await env.seed("near")
    held_a = await env.seed("held-a")
    held_b = await env.seed("held-b")
    await env.propose().handle(env.command([held_a, held_b], "held"))
    other_project = await env.seed("zeta", project="zeta")
    other_subtype = await env.seed("gotcha", subtype="gotcha")
    unreviewed = await env.seed("migrated", accept=False, tags=(MIGRATED,))
    experience = await env.review.capture_experience("exp")
    env.finder.hits[anchor.value] = [
        (other_project.value, ("lexical",)),
        (near.value, ("lexical", "graph")),
        (anchor.value, ("lexical",)),
        (unreviewed.value, ("lexical",)),
        (other_subtype.value, ("graph",)),
        (experience.value, ("graph",)),
        (held_a.value, ("lexical",)),
    ]
    before = graph_digest(env.settings)

    result = await env.scan.handle(_scan(record_id=anchor, hits=7))

    assert graph_digest(env.settings) == before  # read-only
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.anchor_id == anchor.value and group.requires == "agent_or_user"
    assert [(c.record_id, c.rank, c.found_by) for c in group.candidates] == [
        (near.value, 2, ("lexical", "graph"))
    ]
    assert [c.record_id for c in group.conflicts] == [held_a.value]
    assert result.semantic_state == "absent" and result.suppressed_count == 0
    assert result.excluded_unaccepted_migrated == 1
    assert "origin:migrated --all --yes" in result.next_steps[0]
    assert "similarity" not in result.model_dump_json()


async def test_a_scan_without_candidates_emits_no_group(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    anchor = await env.seed("lonely")
    result = await env.scan.handle(_scan(record_id=anchor))
    assert result.groups == () and result.next_steps == () and result.next_cursor is None


async def test_ac05_a_project_scan_pages_anchors_latest_accepted_first(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("p1")
    second = await env.seed("p2")
    third = await env.seed("p3")
    await env.seed("unreviewed-migrated", accept=False, tags=(MIGRATED,))
    await env.seed("elsewhere", project="zeta")
    for anchor, partner in ((first, second), (second, third), (third, first)):
        env.finder.hits[anchor.value] = [(partner.value, ("lexical",))]

    page_one = await env.scan.handle(_scan(project=Key(value="acme"), anchors=2))
    assert [g.anchor_id for g in page_one.groups] == [third.value, second.value]
    assert page_one.next_cursor is not None
    assert page_one.excluded_unaccepted_migrated == 1  # whatever the page

    page_two = await env.scan.handle(
        _scan(project=Key(value="acme"), anchors=2, cursor=page_one.next_cursor)
    )
    assert [g.anchor_id for g in page_two.groups] == [first.value]
    assert page_two.next_cursor is None and page_two.excluded_unaccepted_migrated == 1
    again = await env.scan.handle(_scan(project=Key(value="acme"), anchors=2))
    assert [g.anchor_id for g in again.groups] == [g.anchor_id for g in page_one.groups]
    # a cursor of another scope is refused
    with pytest.raises(InvalidConsolidationError):
        await env.scan.handle(_scan(space_wide=True, cursor=page_one.next_cursor))
    # the number of hits per anchor is bounded
    env.finder.calls.clear()
    await env.scan.handle(_scan(project=Key(value="acme"), hits=2, anchors=1))
    assert env.finder.calls and all(limit == 2 for _, limit in env.finder.calls)


async def test_the_space_wide_scan_covers_records_without_a_project(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    wide_a = await env.seed("w-a", project=None)
    wide_b = await env.seed("w-b", project=None)
    await env.seed("scoped")
    env.finder.hits[wide_a.value] = [(wide_b.value, ("graph",))]
    result = await env.scan.handle(_scan(space_wide=True))
    assert [g.anchor_id for g in result.groups] == [wide_a.value]
    assert result.groups[0].requires == "user"


async def test_the_semantic_state_is_the_least_available_one_seen(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    await env.seed("s1")
    await env.seed("s2")
    for state, expected in (
        ("ready", "ready"),
        ("lagging", "lagging"),
        ("unavailable", "unavailable"),
    ):
        env.finder.semantic_state = state
        result = await env.scan.handle(_scan(project=Key(value="acme")))
        assert result.semantic_state == expected
    empty = await env.scan.handle(_scan(project=Key(value="nothing-here")))
    assert empty.semantic_state == "absent"


async def test_ac06_distinct_dismissals_hide_or_label_the_judged_pair(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    a = await env.seed("j-a")
    b = await env.seed("j-b")
    c = await env.seed("j-c")
    created = await env.propose().handle(env.command([a, b], "j1"))
    await env.reject().handle(env.reject_command(created.consolidation_id or "", "j1-r"))
    other = await env.propose().handle(env.command([a, c], "j2"))
    await env.reject().handle(
        env.reject_command(
            other.consolidation_id or "", "j2-r", kind=DismissalReasonKindEnum.POOR_DRAFT
        )
    )
    env.finder.hits[a.value] = [(b.value, ("lexical",)), (c.value, ("lexical",))]

    hidden = await env.scan.handle(_scan(record_id=a))
    assert [c_.record_id for c_ in hidden.groups[0].candidates] == [c.value]
    assert hidden.suppressed_count == 1

    shown = await env.scan.handle(_scan(record_id=a, include_dismissed=True))
    labels = {c_.record_id: c_.dismissed_in for c_ in shown.groups[0].candidates}
    assert labels == {b.value: created.consolidation_id, c.value: None}
    assert shown.suppressed_count == 0


async def test_scan_errors(consolidation_env: ConsolidationEnv) -> None:
    env = consolidation_env
    anchor = await env.seed("err")
    proposed = await env.seed("err-p", accept=False)
    with pytest.raises(IneligibleConsolidationMemberError):
        await env.scan.handle(_scan(record_id=proposed))
    with pytest.raises(RecordNotFoundError):
        await env.scan.handle(_scan(record_id=RecordId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV")))
    for fields in (
        {},
        {"record_id": anchor, "space_wide": True},
        {"record_id": anchor, "hits": 51},
    ):
        with pytest.raises(InvalidConsolidationError):
            await env.scan.handle(_scan(**fields))

    env.finder.error = IndexRebuildRequiredError("rebuild", {"x": 1})
    with pytest.raises(SimilarityUnavailableError) as error:
        await env.scan.handle(_scan(record_id=anchor))
    assert error.value.metadata["original_code"] == IndexRebuildRequiredError.__error_code__
    env.finder.error = GraphStoreUnavailableError("down", {"phase": "connect"})
    with pytest.raises(GraphStoreUnavailableError):
        await env.scan.handle(_scan(record_id=anchor))
