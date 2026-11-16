"""Resumable consolidation over the pinned Neo4j: AC-07..AC-10, AC-12..AC-14 (handlers)."""

import asyncio
from typing import Any

import pytest
from tests.support.consolidation_support import (
    ConsolidationEnv,
    make_consolidation_env,
    open_keys,
    raw_consolidations,
)
from tests.support.knowledge_neo4j_support import query
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.review_commands import USER, retract_knowledge_command
from tests.support.review_support import (
    CommitFailingFactory,
    count_nodes,
    decisions_of,
    stored_status,
)

from noesis.bounded_context.knowledge.application.handlers.commands.accept_consolidation_handler import (
    AcceptConsolidationCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.replace_link_set_handler import (
    ReplaceLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.services.link_set_request import LinkSetRequest
from noesis.bounded_context.knowledge.domain.value_objects import (
    ConsolidationId,
    DismissalReasonKindEnum,
    RecordId,
    SpaceId,
    Tag,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)
from noesis.exceptions import (
    ConsolidationClosedError,
    ConsolidationMembershipConflictError,
    ConsolidationPartiallyAppliedError,
    GraphStoreUnavailableError,
    IneligibleConsolidationMemberError,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


def _accept(cid: str, key: str | None = "acc", *, actor=AGENT) -> AcceptConsolidationCommand:
    return AcceptConsolidationCommand(
        space_key=DEFAULT_SPACE_KEY,
        actor=actor,
        apply=True,
        idempotency_key=key,
        consolidation_id=ConsolidationId(value=cid),
    )


async def _commits_of(env: ConsolidationEnv, call: Any) -> int:
    """How many committing units of work a successful run of `call(factory)` takes."""
    counter = CommitFailingFactory(env.uow, fail_on=10_000)
    await call(counter)
    return counter.commits


def _produced(env: ConsolidationEnv, cid: str) -> list[str]:
    rows = query(
        env.settings,
        "MATCH (:Consolidation {id: $id})-[:PRODUCED]->(r:Record) RETURN r.id AS id ORDER BY id",
        id=cid,
    )
    return [row["id"] for row in rows]


async def test_ac08_a_crash_at_any_commit_of_a_proposal_resumes_to_the_same_records(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    pair = [await env.seed("c-a"), await env.seed("c-b")]
    total = await _commits_of(env, lambda f: env.propose(f).handle(env.command(pair, "probe")))
    assert total >= 5

    for fail_on in range(1, total + 1):
        first = await env.seed(f"c{fail_on}-a")
        second = await env.seed(f"c{fail_on}-b")
        key = f"crash-{fail_on}"
        command = env.command([first, second], key)
        expected = (
            GraphStoreUnavailableError if fail_on == 1 else ConsolidationPartiallyAppliedError
        )
        with pytest.raises(expected) as error:
            await env.propose(CommitFailingFactory(env.uow, fail_on=fail_on)).handle(command)
        if fail_on == 1:
            assert open_keys(env.settings).count(first.value) == 0  # nothing was written
            continue
        crashed = error.value
        assert isinstance(crashed, ConsolidationPartiallyAppliedError)
        cid = str(crashed.metadata["consolidation_id"])
        assert crashed.metadata["failed"] and crashed.metadata["cause_code"].startswith(
            "INTEGRATION"
        )
        assert any("--idempotency-key " + key in step for step in crashed.next_steps)

        resumed = await env.propose().handle(command)

        assert resumed.consolidation_id == cid and resumed.state == "materialised"
        assert len(resumed.assertions) == 2 and resumed.successor_id
        assert _produced(env, cid) == sorted(
            [resumed.successor_id, *(a.record_id for a in resumed.assertions)]
        )
        # one successor and one assertion per original, whatever the crash point
        rows = query(
            env.settings,
            "MATCH (a:Assertion {subject_id: $n, predicate: 'supersedes'}) RETURN count(a) AS total",
            n=resumed.successor_id,
        )
        assert rows[0]["total"] == 2
        again = await env.propose().handle(command)
        assert again.replayed and again.successor_id == resumed.successor_id
    assert count_nodes(env.settings, "Consolidation") == total  # probe + one per crash point


async def test_ac08_a_resume_rechecks_members_before_unfinished_effects(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("r-a")
    second = await env.seed("r-b")
    command = env.command([first, second], "recheck")
    with pytest.raises(ConsolidationPartiallyAppliedError):
        await env.propose(CommitFailingFactory(env.uow, fail_on=2)).handle(command)
    await env.review.retract_knowledge().handle(retract_knowledge_command(first, "r-ret"))

    with pytest.raises(IneligibleConsolidationMemberError) as error:
        await env.propose().handle(command)

    assert error.value.metadata["cause"] == "lifecycle_changed"
    # the plan was not rewritten and nothing was undone
    assert len(raw_consolidations(env.settings)) == 1


async def test_ac09_a_crash_during_accept_converges_without_a_second_decision(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    pair = [await env.seed("x-a"), await env.seed("x-b")]
    probe = await env.propose().handle(env.command(pair, "probe"))
    total = await _commits_of(
        env, lambda f: env.accept(f).handle(_accept(probe.consolidation_id or "", "probe-acc"))
    )
    assert total >= 6

    for fail_on in range(1, total + 1):
        first = await env.seed(f"a{fail_on}-a")
        second = await env.seed(f"a{fail_on}-b")
        created = await env.propose().handle(env.command([first, second], f"p-{fail_on}"))
        cid = created.consolidation_id or ""
        key = f"acc-{fail_on}"
        with pytest.raises((GraphStoreUnavailableError, ConsolidationPartiallyAppliedError)):
            await env.accept(CommitFailingFactory(env.uow, fail_on=fail_on)).handle(
                _accept(cid, key)
            )

        done = await env.accept().handle(_accept(cid, key))

        assert done.progress == "applied"
        assert {s.outcome for s in done.steps} <= {"accepted", "already_accepted"}
        for record in (created.successor_id, *(a.record_id for a in created.assertions)):
            assert [d["transition"] for d in decisions_of(env.settings, record or "")] == ["accept"]
        for original in (first, second):
            assert [d["transition"] for d in decisions_of(env.settings, original.value)] == [
                "accept",
                "supersede",
            ]


async def test_ac10_a_failed_step_is_an_error_listing_every_step(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("e-a")
    second = await env.seed("e-b")
    created = await env.propose().handle(env.command([first, second], "e1"))
    cid = created.consolidation_id or ""
    # retract the successor behind the handler's back so the first decision fails
    await env.review.retract_knowledge().handle(
        retract_knowledge_command(RecordId(value=created.successor_id or ""), "e-ret")
    )

    with pytest.raises(ConsolidationPartiallyAppliedError) as error:
        await env.accept().handle(_accept(cid))

    metadata = error.value.metadata
    outcomes = {step["target"]: step["outcome"] for step in metadata["steps"]}
    assert outcomes[created.successor_id or ""] == "failed"
    assert [outcomes[a.record_id] for a in created.assertions] == ["not_run", "not_run"]
    assert metadata["progress"] == "successor_retracted" and metadata["consolidation_id"] == cid
    assert any("--idempotency-key acc" in step for step in error.value.next_steps)


async def test_ac07_two_proposals_sharing_a_member_leave_one_reservation(
    neo4j_settings,
) -> None:
    env = make_consolidation_env(neo4j_settings)
    other = make_consolidation_env(neo4j_settings)
    try:
        await env.review.initialise()
        a, b, c = await env.seed("s-a"), await env.seed("s-b"), await env.seed("s-c")

        outcomes = await asyncio.gather(
            env.propose().handle(env.command([a, b], "race-1")),
            other.propose().handle(other.command([b, c], "race-2")),
            return_exceptions=True,
        )

        winners = [o for o in outcomes if not isinstance(o, BaseException)]
        losers = [o for o in outcomes if isinstance(o, BaseException)]
        assert len(winners) == 1 and len(losers) == 1
        assert isinstance(losers[0], ConsolidationMembershipConflictError)
        assert len(raw_consolidations(neo4j_settings)) == 1
        assert b.value in open_keys(neo4j_settings)
    finally:
        await other.client.close()
        await env.client.close()


async def test_ac07_accept_against_reject_has_one_winner(neo4j_settings) -> None:
    env = make_consolidation_env(neo4j_settings)
    other = make_consolidation_env(neo4j_settings)
    try:
        await env.review.initialise()
        _, _, created = await env.propose_pair("ar")
        cid = created.consolidation_id or ""

        outcomes = await asyncio.gather(
            env.accept().handle(_accept(cid, "ar-acc", actor=USER)),
            other.reject().handle(other.reject_command(cid, "ar-rej")),
            return_exceptions=True,
        )

        ok = [o for o in outcomes if not isinstance(o, BaseException)]
        failed = [o for o in outcomes if isinstance(o, BaseException)]
        assert len(ok) == 1 and len(failed) == 1
        assert isinstance(failed[0], ConsolidationClosedError)
        state = raw_consolidations(neo4j_settings)[0]["state"]
        successor = created.successor_id or ""
        if state == "dismissed":  # the loser never performed its opposing side effects
            assert stored_status(neo4j_settings, successor) == "retracted"
        else:
            assert state == "acceptance_started"
            assert stored_status(neo4j_settings, successor) == "accepted"
    finally:
        await other.client.close()
        await env.client.close()


async def test_a_reject_that_crashes_after_dismissal_resumes_with_the_same_key(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    _, _, created = await env.propose_pair("rj")
    cid = created.consolidation_id or ""
    with pytest.raises((GraphStoreUnavailableError, ConsolidationPartiallyAppliedError)):
        await env.reject(CommitFailingFactory(env.uow, fail_on=3)).handle(
            env.reject_command(cid, "rj-1")
        )
    assert raw_consolidations(env.settings)[0]["state"] == "dismissed"

    done = await env.reject().handle(env.reject_command(cid, "rj-1"))

    assert {s.outcome for s in done.steps} <= {"done", "rejected", "already_retracted"}
    assert stored_status(env.settings, created.successor_id or "") == "retracted"
    assert all(stored_status(env.settings, a.record_id) == "retracted" for a in created.assertions)
    replay = await env.reject().handle(env.reject_command(cid, "rj-1"))
    assert replay.replayed


async def test_a_reject_leaves_what_someone_accepted_meanwhile(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    _, _, created = await env.propose_pair("la")
    from tests.support.review_commands import accept_knowledge_command

    await env.review.accept_knowledge().handle(
        accept_knowledge_command(RecordId(value=created.successor_id or ""), "la-n", actor=USER)
    )

    done = await env.reject().handle(env.reject_command(created.consolidation_id or "", "la-r"))

    outcomes = {s.target: s.outcome for s in done.steps}
    assert outcomes[created.successor_id or ""] == "left_accepted"
    assert stored_status(env.settings, created.successor_id or "") == "accepted"


def _link_state(env: ConsolidationEnv) -> dict[str, Any]:
    link_sets = query(
        env.settings, "MATCH (n:LinkSet) RETURN properties(n) AS p ORDER BY p.source_record_id"
    )
    edges = query(
        env.settings,
        "MATCH (a)-[r:LINKS_TO|EMBEDS]->(b) RETURN a.id AS source, b.id AS target, "
        "type(r) AS kind, properties(r) AS p ORDER BY source, target, kind",
    )
    return {"link_sets": link_sets, "edges": edges}


async def _link(env: ConsolidationEnv, source: RecordId, *targets: RecordId) -> None:
    await ReplaceLinkSetHandler(
        uow_factory=env.review.base.persistence.uow_factory, clock=env.review.base.clock
    ).handle(
        LinkSetRequest(
            space_key=DEFAULT_SPACE_KEY,
            source_record_id=source,
            origin_tag=Tag(value="origin:migrated"),
            links=tuple(
                RecordLink(target_record_id=t, link_type="links_to", count=2, anchors=("intro",))
                for t in targets
            ),
            actor=USER,
        )
    )


async def test_ac12_every_original_link_set_and_edge_survives_every_operation(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("l-a")
    second = await env.seed("l-b")
    linker = await env.seed("l-x")
    other = await env.seed("l-y")
    await _link(env, linker, first)  # incoming link to an original
    await _link(env, first, other)  # outgoing link of an original
    await _link(env, second, first)
    before = _link_state(env)
    assert before["link_sets"] and before["edges"]

    created = await env.propose().handle(env.command([first, second], "l1"))
    assert _link_state(env) == before
    await env.propose().handle(env.command([first, second], "l1"))  # replay
    assert _link_state(env) == before
    await env.accept().handle(_accept(created.consolidation_id or ""))
    assert _link_state(env) == before
    assert (
        query(
            env.settings,
            "MATCH (n:LinkSet {source_record_id: $id}) RETURN n",
            id=created.successor_id,
        )
        == []
    )  # the successor inherits no LinkSet
    assert _link_state(env) == before


async def test_ac12_dismissal_leaves_links_alone_too(consolidation_env: ConsolidationEnv) -> None:
    env = consolidation_env
    first = await env.seed("ld-a")
    second = await env.seed("ld-b")
    await _link(env, first, second)
    before = _link_state(env)
    created = await env.propose().handle(env.command([first, second], "ld1"))
    await env.reject().handle(
        env.reject_command(
            created.consolidation_id or "", "ld-r", kind=DismissalReasonKindEnum.OTHER
        )
    )
    assert _link_state(env) == before


async def test_ac13_a_concurrent_link_replacement_is_never_reverted(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("lc-a")
    second = await env.seed("lc-b")
    third = await env.seed("lc-c")
    await _link(env, first, second)
    created = await env.propose().handle(env.command([first, second], "lc1"))

    await _link(env, first, third)  # the source owner replaces the set mid-workflow
    replaced = _link_state(env)
    await env.accept().handle(_accept(created.consolidation_id or ""))

    after = _link_state(env)
    assert after == replaced
    versions = [row["p"]["version"] for row in after["link_sets"]]
    assert versions == [2]


async def test_ac14_an_incoming_link_reaches_the_accepted_successor_only(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    first = await env.seed("n-a")
    second = await env.seed("n-b")
    linker = await env.seed("n-x")
    await _link(env, linker, first)
    space_id = await env.review.space_id()
    reader = Neo4jRecordNeighbourReaderAdapter(env.client)

    async def found() -> dict[str, list[str]]:
        contract = await reader.neighbours([linker.value], space_id=space_id, limit=10)
        return {n.record_id: list(n.supersession_path) for n in contract.neighbours}

    assert set(await found()) == {first.value}
    created = await env.propose().handle(env.command([first, second], "n1"))
    assert set(await found()) == {first.value}  # a proposed successor redirects nothing

    await env.accept().handle(_accept(created.consolidation_id or ""))

    reached = await found()
    assert created.successor_id in reached
    contract = await reader.neighbours([linker.value], space_id=space_id, limit=10)
    successor = next(n for n in contract.neighbours if n.record_id == created.successor_id)
    assert successor.original_target_id == first.value  # the original stays as provenance
    assert linker.value not in reached and SpaceId(value=space_id)


async def test_ac10_a_store_outage_mid_accept_stops_the_remaining_steps(
    consolidation_env: ConsolidationEnv,
) -> None:
    env = consolidation_env
    pair = [await env.seed("o-a"), await env.seed("o-b")]
    probe = await env.propose().handle(env.command(pair, "o-probe"))
    total = await _commits_of(
        env, lambda f: env.accept(f).handle(_accept(probe.consolidation_id or "", "o-probe-acc"))
    )
    interrupted_assertions = 0

    for fail_on in range(2, total + 1):
        first = await env.seed(f"o{fail_on}-a")
        second = await env.seed(f"o{fail_on}-b")
        created = await env.propose().handle(env.command([first, second], f"o-{fail_on}"))
        cid = created.consolidation_id or ""
        try:
            await env.accept(CommitFailingFactory(env.uow, fail_on=fail_on)).handle(
                _accept(cid, f"o-acc-{fail_on}")
            )
        except ConsolidationPartiallyAppliedError as error:
            metadata = error.metadata
            if not str(metadata.get("cause_code", "")).startswith("INTEGRATION"):
                continue
            outcomes = [step["outcome"] for step in metadata["steps"]]
            failed_at = outcomes.index("failed")
            assert outcomes[failed_at + 1 :] == ["not_run"] * (len(outcomes) - failed_at - 1)
            assert metadata["progress"] == "unknown"
            assert metadata["consolidation_id"] == cid
            assert any(f"--idempotency-key o-acc-{fail_on}" in s for s in error.next_steps)
            if failed_at == 1:
                interrupted_assertions += 1
        except GraphStoreUnavailableError:
            continue

        done = await env.accept().handle(_accept(cid, f"o-acc-{fail_on}"))
        assert done.progress == "applied"

    assert interrupted_assertions >= 1
