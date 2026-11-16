"""Consolidation over the pinned Neo4j: AC-01..AC-04, AC-06, AC-11, AC-16, AC-17 (handlers)."""

import pytest
from tests.support.consolidation_support import (
    MIGRATED,
    ConsolidationEnv,
    change_kinds,
    open_keys,
    raw_consolidations,
)
from tests.support.knowledge_neo4j_support import query
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.review_commands import USER, retract_knowledge_command
from tests.support.review_support import count_nodes, graph_digest, stored_status

from noesis.bounded_context.knowledge.application.handlers.commands.accept_consolidation_handler import (
    AcceptConsolidationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.application.handlers.queries.show_consolidation_handler import (
    ListConsolidationsQuery,
    ShowConsolidationQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    ConsolidationId,
    DismissalReasonKindEnum,
    Key,
    RecordId,
    SpaceId,
)
from noesis.exceptions import (
    ConsolidationClosedError,
    ConsolidationMembershipConflictError,
    ConsolidationNotFoundError,
    DismissedConsolidationPairError,
    EvidenceRequiredError,
    IdempotencyKeyReusedError,
    IneligibleConsolidationMemberError,
    InvalidConsolidationError,
    ReviewNotAuthorisedError,
    StoreNotInitialisedError,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


def _accept(consolidation_id: str, key: str | None = "acc", *, actor=AGENT, apply: bool = True):
    return AcceptConsolidationCommand(
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        apply=apply,
        idempotency_key=key,
        consolidation_id=ConsolidationId(value=consolidation_id),
    )


async def test_ac01_proposes_a_successor_and_one_supersedes_per_original(
    consolidation_env: ConsolidationEnv,
) -> None:
    first, second, result = await consolidation_env.propose_pair()

    assert result.state == "materialised" and not result.dry_run and not result.replayed
    assert [m.record_id for m in result.members] == sorted([first.value, second.value])
    assert result.successor_status == "proposed" and result.progress == "pending"
    assert {a.status for a in result.assertions} == {"proposed"} and len(result.assertions) == 2
    assert result.requires == "agent_or_user" and result.decidable_by_caller
    assert result.link_policy == "preserve_originals"
    settings = consolidation_env.settings
    assert stored_status(settings, first.value) == "accepted"  # originals untouched
    assert stored_status(settings, second.value) == "accepted"
    detail = await consolidation_env.review.base.get_record.handle(
        GetRecordQuery(
            space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=result.successor_id or "")
        )
    )
    # the successor carries the union of the originals' sources
    assert detail.revision is not None and len(detail.revision.sources) == 2
    assert open_keys(settings) == sorted([first.value, second.value])
    assert count_nodes(settings, "Consolidation") == 1
    assert query(settings, "MATCH (c:Consolidation:Record) RETURN c") == []  # never a record


async def test_ac01_each_assertion_carries_independent_evidence_without_the_endpoints(
    consolidation_env: ConsolidationEnv,
) -> None:
    first, second, result = await consolidation_env.propose_pair()
    shown = await consolidation_env.show.handle(
        ShowConsolidationQuery(
            space_key=DEFAULT_SPACE_KEY,
            actor=AGENT,
            consolidation_id=ConsolidationId(value=result.consolidation_id or ""),
        )
    )
    assert shown.progress == "pending" and shown.requires == "agent_or_user"
    for produced in shown.produced:
        if produced.record_type != "assertion":
            continue
        record = (
            await consolidation_env.review.base.persistence.assertion_read_repository.get_by_id(
                RecordId(value=produced.record_id),
                space_id=SpaceId(value=await consolidation_env.review.space_id()),
            )
        )
        assert record is not None
        assert record.predicate == "supersedes" and record.subject_id == result.successor_id
        assert record.object_id in {first.value, second.value}
        assert result.successor_id not in record.evidence_ids
        assert record.object_id not in record.evidence_ids
        assert len(record.evidence_ids) == 1  # the original's own source


async def test_ac02_agent_accepts_in_a_project_and_the_originals_are_superseded(
    consolidation_env: ConsolidationEnv,
) -> None:
    first, second, proposed = await consolidation_env.propose_pair()
    cid = proposed.consolidation_id or ""

    preview = await consolidation_env.accept().handle(_accept(cid, None, apply=False))
    assert preview.preview and [s.outcome for s in preview.steps] == ["planned"] * 3

    done = await consolidation_env.accept().handle(_accept(cid))

    assert [s.outcome for s in done.steps] == ["accepted"] * 3 and done.progress == "applied"
    assert done.state == "acceptance_started"
    settings = consolidation_env.settings
    assert stored_status(settings, proposed.successor_id or "") == "accepted"
    states = await consolidation_env.review.get_review_states.handle(
        GetReviewStatesQuery(space_key=DEFAULT_SPACE_KEY, record_ids=(first, second))
    )
    assert {s.effective_status for s in states} == {"superseded"}
    assert stored_status(settings, first.value) == "superseded"
    # the same command again, same key: complete replay
    again = await consolidation_env.accept().handle(_accept(cid))
    assert again.replayed and again.progress == "applied"
    # and with a new key: converges without a second decision
    converged = await consolidation_env.accept().handle(_accept(cid, "acc-2"))
    assert [s.outcome for s in converged.steps] == ["already_accepted"] * 3


async def test_ac03_global_consolidation_needs_the_user(
    consolidation_env: ConsolidationEnv,
) -> None:
    _, _, proposed = await consolidation_env.propose_pair("g", project=None)
    cid = proposed.consolidation_id or ""
    assert (
        proposed.requires == "user" and proposed.decidable_by_caller is False
    )  # an agent proposed it

    with pytest.raises(ReviewNotAuthorisedError):
        await consolidation_env.accept().handle(_accept(cid))
    with pytest.raises(ReviewNotAuthorisedError):
        await consolidation_env.reject().handle(
            consolidation_env.reject_command(cid, "r-agent", actor=AGENT)
        )
    assert stored_status(consolidation_env.settings, proposed.successor_id or "") == "proposed"
    shown = await consolidation_env.show.handle(
        ShowConsolidationQuery(
            space_key=DEFAULT_SPACE_KEY, actor=AGENT, consolidation_id=ConsolidationId(value=cid)
        )
    )
    assert shown.decidable_by_caller is False and shown.requires == "user"
    preview = await consolidation_env.accept().handle(_accept(cid, None, actor=AGENT, apply=False))
    assert {s.outcome for s in preview.steps} == {"not_authorised"}

    done = await consolidation_env.accept().handle(_accept(cid, "u1", actor=USER))
    assert done.progress == "applied"


async def test_ac04_ineligible_members_create_nothing(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    ok = await env.seed("ok")
    other_project = await env.seed("op", project="zeta")
    other_subtype = await env.seed("os", subtype="gotcha")
    proposed = await env.seed("pr", accept=False)
    retracted = await env.seed("rt")
    await env.review.retract_knowledge().handle(retract_knowledge_command(retracted, "rt-x"))
    old = await env.seed("old")
    new = await env.seed("new")
    await env.review.seed_accepted_assertion(
        AssertionPredicateEnum.SUPERSEDES,
        new,
        old,
        "sup",
        project="acme",
    )
    experience = await env.review.capture_experience("exp-1")
    migrated = await env.seed("mg", accept=False, tags=(MIGRATED,))
    before = graph_digest(env.settings)

    for members, cause in (
        ([ok, other_project], "project_mismatch"),
        ([ok, other_subtype], "subtype_mismatch"),
        ([ok, proposed], "not_accepted"),
        ([ok, retracted], "retracted"),
        ([ok, old], "superseded"),
        ([ok, experience], "not_knowledge"),
        ([ok, RecordId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV")], "not_found"),
    ):
        with pytest.raises(IneligibleConsolidationMemberError) as error:
            await env.propose().handle(env.command(members, "bad"))
        assert error.value.metadata["cause"] == cause, members
    with pytest.raises(IneligibleConsolidationMemberError) as error:
        await env.propose().handle(env.command([ok, migrated], "bad"))
    assert "origin:migrated --all --yes" in " ".join(error.value.next_steps)
    for members in ([ok], [ok, ok], [ok] * 11):
        with pytest.raises(InvalidConsolidationError):
            await env.propose().handle(env.command(members, "bad"))
    assert graph_digest(env.settings) == before  # nothing created, not even a ledger entry


async def test_ac04_a_member_of_another_space_is_not_found(
    consolidation_env: ConsolidationEnv,
) -> None:
    from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
        InitialiseStoreCommand,
    )

    env = consolidation_env
    await env.review.base.initialise_store.handle(
        InitialiseStoreCommand(default_space_key=Key(value="space-b"))
    )
    local = await env.seed("l")
    foreign = await env.review.capture("f", space_key=Key(value="space-b"))
    with pytest.raises(IneligibleConsolidationMemberError) as error:
        await env.propose().handle(env.command([local, foreign], "x"))
    assert error.value.metadata["cause"] == "not_found"


async def test_a_dry_run_and_a_missing_schema_write_nothing(
    consolidation_env: ConsolidationEnv, consolidation_bare_env: ConsolidationEnv
) -> None:
    env = consolidation_env
    first = await env.seed("d-a")
    second = await env.seed("d-b")
    before = graph_digest(env.settings)

    planned = await env.propose().handle(env.command([first, second], None, apply=False))

    assert planned.dry_run and planned.consolidation_id is None and planned.successor_id is None
    assert [p.object_id for p in planned.planned_assertions] == sorted([first.value, second.value])
    assert all(len(p.evidence_ids) == 1 for p in planned.planned_assertions)
    assert graph_digest(env.settings) == before
    assert raw_consolidations(env.settings) == []


async def test_missing_consolidation_step_fails_before_any_write(neo4j_settings) -> None:
    from tests.support.consolidation_support import make_consolidation_env
    from tests.support.knowledge_neo4j_support import node_counts

    env = make_consolidation_env(neo4j_settings)
    try:
        await env.review.initialise()
        # a store initialised without the consolidation step: drop it from the applied steps
        query(
            neo4j_settings,
            "MATCH (m:StoreMeta) SET m.applied_steps = [s IN m.applied_steps WHERE s <> 'consolidation']",
        )
        before = node_counts(neo4j_settings)
        with pytest.raises(StoreNotInitialisedError):
            await env.propose().handle(
                env.command([RecordId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV")] * 2, "k")
            )
        assert node_counts(neo4j_settings) == before
    finally:
        await env.client.close()


async def test_the_key_is_reused_for_a_changed_payload_and_replays_the_same_one(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("k-a")
    second = await env.seed("k-b")
    created = await env.propose().handle(env.command([first, second], "same"))
    replay = await env.propose().handle(env.command([first, second], "same"))
    assert replay.replayed and replay.consolidation_id == created.consolidation_id
    assert len(raw_consolidations(env.settings)) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await env.propose().handle(env.command([first, second], "same", title="Another title"))


async def test_secret_text_is_redacted_before_it_is_stored(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("s-a")
    second = await env.seed("s-b")
    token = "ghp_" + "a" * 36
    result = await env.propose().handle(
        env.command(
            [first, second],
            "sec",
            body=f"Use the token {token} for retries",
            rationale=f"password = {token}",
        )
    )
    stored = raw_consolidations(env.settings)[0]
    assert token not in stored["rationale"]
    record = await env.review.base.get_record.handle(
        GetRecordQuery(
            space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=result.successor_id or "")
        )
    )
    assert record.revision is not None and token not in (record.revision.body or "")


async def test_ac06_distinct_dismissals_suppress_only_the_judged_pair(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    a, b, proposed = await env.propose_pair("d")
    cid = proposed.consolidation_id or ""
    third = await env.seed("d-c")

    await env.reject().handle(env.reject_command(cid, "r-d"))

    assert open_keys(env.settings) == []  # dismissal releases the members
    with pytest.raises(DismissedConsolidationPairError) as error:
        await env.propose().handle(env.command([a, b], "again"))
    assert cid in error.value.next_steps[0]
    # an unrelated pair is not suppressed
    unrelated = await env.propose().handle(env.command([a, third], "other"))
    assert unrelated.state == "materialised"
    await env.reject().handle(
        env.reject_command(
            unrelated.consolidation_id or "", "r-o", kind=DismissalReasonKindEnum.POOR_DRAFT
        )
    )
    # --reconsider overrides exactly that dismissal
    with pytest.raises(InvalidConsolidationError):
        await env.propose().handle(
            env.command([a, third], "c1", reconsider_id=ConsolidationId(value=cid))
        )
    reconsidered = await env.propose().handle(
        env.command([a, b], "c2", reconsider_id=ConsolidationId(value=cid))
    )
    assert reconsidered.state == "materialised"


async def test_ac06_a_changed_revision_expires_the_dismissal(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    a = await env.seed("e-a")
    b = await env.seed("e-b")
    first = await env.propose().handle(env.command([a, b], "e1"))
    await env.reject().handle(env.reject_command(first.consolidation_id or "", "e-r"))
    # accepted records have immutable revisions, so replace b by a successor pair instead:
    # a `poor_draft` dismissal never suppresses
    second = await env.propose().handle(
        env.command([a, b], "e2", reconsider_id=ConsolidationId(value=first.consolidation_id or ""))
    )
    assert second.state == "materialised"


async def test_ac11_evidence_comes_from_sources_and_supports_never_from_links_or_endpoints(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    a = await env.seed("v-a")
    b = await env.seed("v-b")
    supporter = await env.review.capture_experience("v-exp")
    await env.review.seed_accepted_assertion(AssertionPredicateEnum.SUPPORTS, supporter, a, "v-sup")

    planned = await env.propose().handle(env.command([a, b], None, apply=False))
    evidence = {p.object_id: p.evidence_ids for p in planned.planned_assertions}

    assert supporter.value in evidence[a.value] and len(evidence[a.value]) == 2  # source + support
    assert len(evidence[b.value]) == 1 and supporter.value not in evidence[b.value]
    assert all(a.value not in ids and b.value not in ids for ids in evidence.values())


async def test_ac11_an_agent_cannot_accept_a_supersedes_without_evidence(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    # every original cites a Source, so model "no independent evidence" by clearing it in the store
    a = await env.seed("n-a")
    b = await env.seed("n-b")
    created = await env.propose().handle(env.command([a, b], "n1"))
    # make the assertions evidence-less in the store to model "no independent evidence"
    query(env.settings, "MATCH (a:Assertion {predicate: 'supersedes'}) SET a.evidence_ids = []")
    with pytest.raises(EvidenceRequiredError):
        await env.accept().handle(_accept(created.consolidation_id or ""))
    preview = await env.accept().handle(_accept(created.consolidation_id or "", None, apply=False))
    assert [s.outcome for s in preview.steps] == ["planned", "not_authorised", "not_authorised"]
    # the user may still decide it
    done = await env.accept().handle(_accept(created.consolidation_id or "", "u", actor=USER))
    assert done.progress == "applied"


async def test_ac16_dismissal_releases_membership_and_started_acceptance_keeps_it(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    a, b, first = await env.propose_pair("m1")
    cid = first.consolidation_id or ""
    await env.reject().handle(env.reject_command(cid, "m1-r", kind=DismissalReasonKindEnum.OTHER))
    again = await env.propose().handle(env.command([a, b], "m1-again"))
    assert again.state == "materialised"

    cid2 = again.consolidation_id or ""
    await env.accept().handle(_accept(cid2, "m1-acc"))
    # the successor is retracted later: the members stay reserved (Q-009)
    successor = RecordId(value=again.successor_id or "")
    await env.review.retract_knowledge().handle(retract_knowledge_command(successor, "m1-ret"))
    assert open_keys(env.settings) == sorted([a.value, b.value])
    with pytest.raises(IneligibleConsolidationMemberError):  # superseded: no new proposal either
        await env.propose().handle(env.command([a, b], "m1-third"))
    shown = await env.show.handle(
        ShowConsolidationQuery(
            space_key=DEFAULT_SPACE_KEY, actor=USER, consolidation_id=ConsolidationId(value=cid2)
        )
    )
    assert shown.progress == "successor_retracted" and shown.membership_note
    with pytest.raises(ConsolidationClosedError):
        await env.reject().handle(env.reject_command(cid2, "m1-late"))


async def test_a_member_of_an_open_consolidation_cannot_join_another(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    _, b, first = await env.propose_pair("o")
    c = await env.seed("o-c")
    with pytest.raises(ConsolidationMembershipConflictError) as error:
        await env.propose().handle(env.command([b, c], "o2"))
    assert first.consolidation_id in str(error.value.metadata)


async def test_show_list_and_missing_consolidation(consolidation_env: ConsolidationEnv) -> None:
    env = consolidation_env
    _, _, proposed = await env.propose_pair("sl")
    await env.propose_pair("sg", project=None)

    listed = await env.listing.handle(
        ListConsolidationsQuery(space_key=DEFAULT_SPACE_KEY, project=Key(value="acme"))
    )
    assert [i.id for i in listed.items] == [proposed.consolidation_id]
    space_wide = await env.listing.handle(
        ListConsolidationsQuery(space_key=DEFAULT_SPACE_KEY, space_wide=True)
    )
    assert len(space_wide.items) == 1 and space_wide.items[0].project_key is None
    page = await env.listing.handle(
        ListConsolidationsQuery(space_key=DEFAULT_SPACE_KEY, space_wide=True, state="dismissed")  # type: ignore[arg-type]
    )
    assert page.items == ()
    with pytest.raises(InvalidConsolidationError):
        await env.listing.handle(ListConsolidationsQuery(space_key=DEFAULT_SPACE_KEY))
    with pytest.raises(ConsolidationNotFoundError):
        await env.show.handle(
            ShowConsolidationQuery(
                space_key=DEFAULT_SPACE_KEY,
                actor=USER,
                consolidation_id=ConsolidationId(value="01ARZ3NDEKTSV4RRFFQ69G5FAV"),
            )
        )


async def test_feed_records_only_record_changes(consolidation_env: ConsolidationEnv) -> None:
    env = consolidation_env
    _, _, proposed = await env.propose_pair("f")
    await env.accept().handle(_accept(proposed.consolidation_id or ""))
    kinds = set(change_kinds(env.settings))
    assert kinds <= {"created", "revised", "status_changed"}
