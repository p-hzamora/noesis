"""AcceptAssertionHandler (FR-004..FR-009, FR-016; AC-004..AC-006, AC-013, AC-015, AC-022)."""

import pytest
from tests.support.knowledge_support import AGENT
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    repair_command,
    retract_knowledge_command,
)
from tests.support.review_fakes import (
    RecordingUowFactory,
    ReviewEnv,
    force_status,
    make_review_env,
    seed_assertion,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import AcceptResultDto
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewTransitionEnum,
)
from noesis.exceptions import (
    EvidenceRequiredError,
    GraphStoreUnavailableError,
    IdempotencyKeyReusedError,
    InvalidStatusTransitionError,
    RecordNotFoundError,
    ReferenceNotAcceptableError,
    ReviewNotAuthorisedError,
)

pytestmark = pytest.mark.unit

SUPPORTS = AssertionPredicateEnum.SUPPORTS
SUPERSEDES = AssertionPredicateEnum.SUPERSEDES
PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED
SUPERSEDED, RETRACTED = RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED


def effects_of(result: AcceptResultDto) -> list[tuple[str, str, str | None]]:
    return [(e.record_id, e.outcome, e.reason) for e in result.effects]


def untouched(env: ReviewEnv, *ids: RecordId) -> None:
    for record_id in ids:
        record = env.store.knowledge.get(record_id.value) or env.store.assertions[record_id.value]
        assert record.decision_seq == 0
        assert record.latest_decision is None
    assert not [e for e in env.store.ledger.values() if e.command.startswith("review.")]


async def supersession(
    env: ReviewEnv, *, project: str | None = None, subject_status: RecordStatusEnum = ACCEPTED
) -> tuple[RecordId, RecordId, RecordId]:
    """N (subject), O (object) and the proposed S 'N supersedes O', with one evidence record."""
    evidence = await seed_experience(env, f"e-{len(env.store.ledger)}")
    n = await seed_knowledge(
        env, f"n{len(env.store.ledger)}", project=project, status=subject_status
    )
    o = await seed_knowledge(env, f"o{len(env.store.ledger)}", project=project, status=ACCEPTED)
    s = await seed_assertion(env, SUPERSEDES, n, o, project=project, evidence=(evidence,))
    return n, o, s


async def test_agent_accepts_a_project_assertion_that_has_evidence() -> None:
    env = await make_review_env()
    experience = await seed_experience(env)
    claim = await seed_knowledge(env, "c1", project="acme", status=ACCEPTED)
    assertion = await seed_assertion(
        env, SUPPORTS, experience, claim, project="acme", evidence=(experience,)
    )

    result = await env.accept_assertion().handle(accept_assertion_command(assertion, "a1"))

    stored = env.store.assertions[assertion.value]
    assert (result.id, result.type, result.status) == (assertion.value, "assertion", "accepted")
    assert (result.pinned_revision, result.decision_seq, result.basis) == (
        None,
        1,
        "agent_project",
    )
    assert (result.applied, result.replayed, result.effects) == (True, False, ())
    assert stored.status is ACCEPTED
    decision = stored.latest_decision
    assert decision is not None
    assert (decision.transition, decision.actor, decision.pinned_revision) == (
        ReviewTransitionEnum.ACCEPT,
        AGENT,
        None,
    )
    ledger = env.store.ledger[(env.space_id.value, "a1")]
    assert (ledger.command, ledger.record_id) == ("review.accept", assertion)
    assert "pending_effect" not in ledger.extra


async def test_agent_needs_evidence_but_the_user_does_not() -> None:
    """AC-013."""
    env = await make_review_env()
    experience = await seed_experience(env)
    claim = await seed_knowledge(env, "c1", project="acme", status=ACCEPTED)
    assertion = await seed_assertion(env, SUPPORTS, experience, claim, project="acme")

    with pytest.raises(EvidenceRequiredError):
        await env.accept_assertion().handle(accept_assertion_command(assertion, "a1"))
    untouched(env, assertion)

    result = await env.accept_assertion().handle(
        accept_assertion_command(assertion, "a2", actor=USER)
    )
    assert (result.status, result.basis) == ("accepted", "user")


async def test_agent_cannot_accept_a_global_supersedes_and_nothing_changes() -> None:
    """AC-005."""
    env = await make_review_env()
    n, o, s = await supersession(env)

    with pytest.raises(ReviewNotAuthorisedError):
        await env.accept_assertion().handle(accept_assertion_command(s))

    assert env.store.assertions[s.value].status is PROPOSED
    assert env.store.knowledge[o.value].status is ACCEPTED
    untouched(env, s, o, n)


async def test_agent_may_accept_a_supersedes_inside_one_project() -> None:
    """AC-005, positive control."""
    env = await make_review_env()
    _, o, s = await supersession(env, project="acme")

    result = await env.accept_assertion().handle(accept_assertion_command(s))

    assert effects_of(result) == [(o.value, "applied", None)]
    assert env.store.knowledge[o.value].status is SUPERSEDED


async def test_accepted_supersedes_marks_the_object_superseded_with_its_own_decision() -> None:
    """AC-004: UoW 1 accepts S and notes the pending effect, UoW 2 supersedes O."""
    env = await make_review_env()
    n, o, s = await supersession(env)

    result = await env.accept_assertion().handle(accept_assertion_command(s, "ac004", actor=USER))

    assert (result.status, result.basis, result.applied) == ("accepted", "user", True)
    assert effects_of(result) == [(o.value, "applied", None)]
    assert env.store.assertions[s.value].status is ACCEPTED
    assert env.store.assertions[s.value].decision_seq == 1
    obj = env.store.knowledge[o.value]
    assert obj.status is SUPERSEDED
    assert obj.superseded_by_assertion_id == s
    decision = obj.latest_decision
    assert decision is not None
    assert (decision.transition, decision.from_status, decision.to_status) == (
        ReviewTransitionEnum.SUPERSEDE,
        ACCEPTED,
        SUPERSEDED,
    )
    assert (decision.cause_assertion_id, decision.basis, decision.actor) == (
        s,
        DecisionBasisEnum.SUPERSESSION_EFFECT,
        USER,
    )
    assert env.store.knowledge[n.value].status is ACCEPTED
    ledger = env.store.ledger[(env.space_id.value, "ac004")]
    assert ledger.extra["pending_effect"] == {"object_id": o.value}


async def test_supersedes_with_a_proposed_subject_is_not_acceptable_until_it_is_accepted() -> None:
    """AC-022 and flow 5."""
    env = await make_review_env()
    n, o, s = await supersession(env, subject_status=PROPOSED)

    with pytest.raises(ReferenceNotAcceptableError):
        await env.accept_assertion().handle(accept_assertion_command(s, actor=USER))

    assert env.store.assertions[s.value].status is PROPOSED
    assert env.store.knowledge[o.value].status is ACCEPTED
    untouched(env, s, o)

    force_status(env, n, ACCEPTED)
    result = await env.accept_assertion().handle(accept_assertion_command(s, "again", actor=USER))
    assert effects_of(result) == [(o.value, "applied", None)]


async def test_reverse_supersession_is_not_acceptable_once_the_first_took_effect() -> None:
    env = await make_review_env()
    n, o, s = await supersession(env)
    await env.accept_assertion().handle(accept_assertion_command(s, "first", actor=USER))
    reverse = await seed_assertion(env, SUPERSEDES, o, n)

    with pytest.raises(ReferenceNotAcceptableError):
        await env.accept_assertion().handle(accept_assertion_command(reverse, actor=USER))

    assert env.store.knowledge[n.value].status is ACCEPTED


@pytest.mark.parametrize("endpoint_status", [RETRACTED, SUPERSEDED])
@pytest.mark.parametrize("which", ["subject", "object"])
async def test_an_endpoint_that_is_retracted_or_superseded_is_not_acceptable(
    which: str, endpoint_status: RecordStatusEnum
) -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "c1", status=ACCEPTED)
    object_ = await seed_knowledge(env, "c2", status=ACCEPTED)
    assertion = await seed_assertion(env, SUPPORTS, subject, object_)
    force_status(env, subject if which == "subject" else object_, endpoint_status)

    with pytest.raises(ReferenceNotAcceptableError):
        await env.accept_assertion().handle(accept_assertion_command(assertion, actor=USER))

    assert env.store.assertions[assertion.value].status is PROPOSED


async def test_an_endpoint_that_is_effectively_superseded_is_not_acceptable() -> None:
    """S1 accepted with its effect pending on O: O is stored accepted but effectively superseded."""
    env = await make_review_env()
    _, o, s1 = await supersession(env)
    crash = RecordingUowFactory(env.store, fail_on_commit=2)
    with pytest.raises(GraphStoreUnavailableError):
        await env.accept_assertion(crash).handle(accept_assertion_command(s1, "k1", actor=USER))
    assert env.store.knowledge[o.value].status is ACCEPTED
    n2 = await seed_knowledge(env, "n2", status=ACCEPTED)
    s2 = await seed_assertion(env, SUPERSEDES, n2, o)

    with pytest.raises(ReferenceNotAcceptableError):
        await env.accept_assertion().handle(accept_assertion_command(s2, "k2", actor=USER))

    assert env.store.assertions[s2.value].status is PROPOSED


@pytest.mark.parametrize("status", [ACCEPTED, SUPERSEDED, RETRACTED])
async def test_accepting_an_assertion_that_is_not_proposed_is_an_invalid_transition(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "c1", status=ACCEPTED)
    object_ = await seed_knowledge(env, "c2", status=ACCEPTED)
    assertion = await seed_assertion(env, SUPPORTS, subject, object_, status=status)

    with pytest.raises(InvalidStatusTransitionError):
        await env.accept_assertion().handle(accept_assertion_command(assertion, actor=USER))

    assert env.store.assertions[assertion.value].status is status


async def test_unknown_assertion_is_not_found() -> None:
    env = await make_review_env()

    with pytest.raises(RecordNotFoundError):
        await env.accept_assertion().handle(
            accept_assertion_command(RecordId(value="7" + "Z" * 25))
        )


async def test_preview_runs_the_checks_and_writes_nothing() -> None:
    env = await make_review_env()
    _, o, s = await supersession(env)
    commits = env.store.commits

    result = await env.accept_assertion().handle(
        accept_assertion_command(s, None, actor=USER, apply=False)
    )

    assert (result.applied, result.status) == (False, "accepted")
    assert env.store.commits == commits
    assert env.store.knowledge[o.value].status is ACCEPTED
    untouched(env, s, o)


async def test_replay_returns_the_first_result_and_the_key_cannot_serve_another_request() -> None:
    """AC-015."""
    env = await make_review_env()
    _, o, s = await supersession(env, project="acme")
    first = await env.accept_assertion().handle(accept_assertion_command(s, "same"))
    commits = env.store.commits

    again = await env.accept_assertion().handle(accept_assertion_command(s, "same"))

    assert again.replayed is True
    assert (again.status, again.decision_seq, effects_of(again)) == (
        first.status,
        first.decision_seq,
        effects_of(first),
    )
    assert env.store.commits == commits
    assert len(env.store.decisions[s.value]) == 1
    assert len(env.store.decisions[o.value]) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await env.accept_assertion().handle(accept_assertion_command(s, "same", reason="other"))


async def test_interrupted_supersession_reads_as_superseded_and_converges_on_replay() -> None:
    """AC-006: the process dies between UoW 1 and UoW 2."""
    env = await make_review_env()
    _, o, s = await supersession(env)
    command = accept_assertion_command(s, "ac006", actor=USER)

    with pytest.raises(GraphStoreUnavailableError):
        await env.accept_assertion(RecordingUowFactory(env.store, fail_on_commit=2)).handle(command)

    assert env.store.assertions[s.value].status is ACCEPTED
    assert env.store.knowledge[o.value].status is ACCEPTED
    [state] = await env.get_review_states.handle(
        GetReviewStatesQuery(space_key=Key(value="default"), record_ids=(o,))
    )
    assert (state.status, state.effective_status, state.authority) == (
        "accepted",
        "superseded",
        "superseded",
    )

    replay = await env.accept_assertion().handle(command)

    assert effects_of(replay) == [(o.value, "applied", None)]
    assert (replay.status, replay.decision_seq) == ("accepted", 1)
    assert env.store.knowledge[o.value].status is SUPERSEDED
    assert env.store.assertions[s.value].decision_seq == 1
    assert len(env.store.decisions[s.value]) == 1
    nothing_pending = await env.repair().handle(repair_command(apply=False))
    assert nothing_pending.effects == ()


async def test_replay_after_the_object_was_retracted_skips_the_effect() -> None:
    """Edge: O retracted before the effect ran; O keeps reading superseded."""
    env = await make_review_env()
    _, o, s = await supersession(env)
    command = accept_assertion_command(s, "k1", actor=USER)
    with pytest.raises(GraphStoreUnavailableError):
        await env.accept_assertion(RecordingUowFactory(env.store, fail_on_commit=2)).handle(command)
    await env.retract_knowledge().handle(retract_knowledge_command(o, "r-o"))
    decisions_on_o = len(env.store.decisions[o.value])

    replay = await env.accept_assertion().handle(command)

    assert effects_of(replay) == [(o.value, "skipped", "object_not_accepted")]
    assert env.store.knowledge[o.value].status is RETRACTED
    assert len(env.store.decisions[o.value]) == decisions_on_o
    [state] = await env.get_review_states.handle(
        GetReviewStatesQuery(space_key=Key(value="default"), record_ids=(o,))
    )
    assert (state.status, state.effective_status) == ("retracted", "superseded")
    assert (await env.repair().handle(repair_command(apply=False))).effects == ()
