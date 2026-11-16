"""C4 writes append to C5a's change feed in the write's own unit of work (20-review: change feed; AC-019)."""

from collections.abc import Callable

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.knowledge_support import FakeKnowledgeStore, FakeKnowledgeUnitOfWork
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    accept_knowledge_command,
    apply_supersession_command,
    propose_command,
    retract_assertion_command,
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

from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import GraphStoreUnavailableError, ReviewNotAuthorisedError

pytestmark = pytest.mark.unit

SUPPORTS = AssertionPredicateEnum.SUPPORTS
SUPERSEDES = AssertionPredicateEnum.SUPERSEDES
PROPOSED, ACCEPTED = RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED

Entry = tuple[str, str, str, int | None, str | None]


def feed_after(env: ReviewEnv, mark: int) -> list[Entry]:
    """The entries appended after `mark` (a count taken with `len(env.store.changes)`)."""
    return [
        (c.change_kind, c.record_type, c.record_id, c.revision, c.status)
        for c in env.store.changes[mark:]
    ]


class _TracingUow(FakeKnowledgeUnitOfWork):
    """Logs, per commit, the records the unit of work saved and the changes it staged."""

    def __init__(self, store: FakeKnowledgeStore, log: list[tuple[set[str], set[str]]]) -> None:
        super().__init__(store)
        self._log = log

    async def commit(self) -> None:
        staged = self._staged
        saved = {
            *(k.id.value for k in staged.knowledge_saves),
            *(a.id.value for a in staged.assertion_saves),
            *staged.assertions,
        }
        self._log.append((saved, {c.record_id for c in staged.changes}))
        await super().commit()


def tracing(env: ReviewEnv, log: list[tuple[set[str], set[str]]]) -> Callable[[], _TracingUow]:
    return lambda: _TracingUow(env.store, log)


async def test_ac019_change_feed_entries_unit() -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    k = await seed_knowledge(env, "k", project="acme")
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    old = await seed_knowledge(env, "old", status=ACCEPTED)
    mark = len(env.store.changes)

    proposed = await env.propose_assertion().handle(
        propose_command(SUPPORTS, subject, object_, "pa")
    )
    a = RecordId(value=proposed.id)
    assert feed_after(env, mark) == [("created", "assertion", a.value, None, "proposed")]

    mark = len(env.store.changes)
    await env.accept_assertion().handle(accept_assertion_command(a, "aa", actor=USER))
    assert feed_after(env, mark) == [("status_changed", "assertion", a.value, None, "accepted")]

    mark = len(env.store.changes)
    await env.accept_knowledge().handle(accept_knowledge_command(k, "ak", expected=1))
    assert feed_after(env, mark) == [("status_changed", "knowledge", k.value, 1, "accepted")]

    evidence = await seed_experience(env, "ev")
    sup = RecordId(
        value=(
            await env.propose_assertion().handle(
                propose_command(SUPERSEDES, n, old, "ps", evidence=(evidence,))
            )
        ).id
    )
    mark = len(env.store.changes)
    await env.accept_assertion().handle(accept_assertion_command(sup, "as", actor=USER))
    assert feed_after(env, mark) == [
        ("status_changed", "assertion", sup.value, None, "accepted"),
        ("status_changed", "knowledge", old.value, 1, "superseded"),
    ]


async def test_ac019_change_feed_refusal_preview_and_replay_append_nothing_unit() -> None:
    env = await make_review_env()
    k = await seed_knowledge(env, "k")  # space-wide: an agent may not accept it
    accepted = await seed_knowledge(env, "acc", project="acme")
    await env.accept_knowledge().handle(accept_knowledge_command(accepted, "first"))
    mark = len(env.store.changes)

    with pytest.raises(ReviewNotAuthorisedError):
        await env.accept_knowledge().handle(accept_knowledge_command(k, "refused"))
    await env.accept_knowledge().handle(
        accept_knowledge_command(k, "preview", actor=USER, apply=False)
    )
    replay = await env.accept_knowledge().handle(accept_knowledge_command(accepted, "first"))

    assert replay.replayed is True
    assert feed_after(env, mark) == []


async def test_ac019_change_feed_assertion_replay_and_preview_append_nothing_unit() -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    a = await seed_assertion(env, SUPPORTS, subject, object_)
    await env.accept_assertion().handle(accept_assertion_command(a, "first", actor=USER))
    b = await seed_assertion(env, SUPPORTS, object_, subject)
    mark = len(env.store.changes)

    await env.accept_assertion().handle(accept_assertion_command(b, "pv", actor=USER, apply=False))
    await env.retract_assertion().handle(
        retract_assertion_command(b, "pr", actor=USER, apply=False)
    )
    replay = await env.accept_assertion().handle(accept_assertion_command(a, "first", actor=USER))

    assert replay.replayed is True
    assert feed_after(env, mark) == []


async def test_ac019_change_feed_skipped_supersession_effect_appends_nothing_unit() -> None:
    env = await make_review_env()
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    o = await seed_knowledge(env, "o", status=RecordStatusEnum.RETRACTED)
    s = await seed_assertion(env, SUPERSEDES, n, o, status=ACCEPTED)
    mark = len(env.store.changes)

    effect = await env.apply_supersession().handle(apply_supersession_command(s, o))

    assert effect.outcome != "applied"
    assert feed_after(env, mark) == []


async def test_ac019_change_feed_supersede_effect_on_an_assertion_unit() -> None:
    env = await make_review_env()
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    old = await seed_assertion(env, SUPPORTS, subject, object_, status=ACCEPTED)
    s = await seed_assertion(env, SUPERSEDES, n, old, status=ACCEPTED)
    mark = len(env.store.changes)

    effect = await env.apply_supersession().handle(apply_supersession_command(s, old))

    assert effect.outcome == "applied"
    assert feed_after(env, mark) == [("status_changed", "assertion", old.value, None, "superseded")]


@pytest.mark.parametrize(
    ("status", "head"),
    [(PROPOSED, 1), (PROPOSED, 2), (ACCEPTED, 1)],
    ids=["reject-head-1", "reject-head-2", "retract-accepted"],
)
async def test_ac019_change_feed_knowledge_reject_or_retract_unit(
    status: RecordStatusEnum, head: int
) -> None:
    env = await make_review_env()
    k = await seed_knowledge(env, "k")
    if head == 2:
        await env.base.revise_knowledge.handle(revise_command(k, "rv", expected=1))
    force_status(env, k, status)
    mark = len(env.store.changes)

    await env.retract_knowledge().handle(retract_knowledge_command(k, "r"))

    assert feed_after(env, mark) == [("status_changed", "knowledge", k.value, head, "retracted")]


@pytest.mark.parametrize("status", [PROPOSED, ACCEPTED])
async def test_ac019_change_feed_assertion_reject_or_retract_unit(
    status: RecordStatusEnum,
) -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    a = await seed_assertion(env, SUPPORTS, subject, object_, status=status)
    mark = len(env.store.changes)

    await env.retract_assertion().handle(retract_assertion_command(a, "r"))

    assert feed_after(env, mark) == [("status_changed", "assertion", a.value, None, "retracted")]


async def test_ac019_change_feed_is_staged_in_the_unit_of_work_of_the_save_unit() -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    k = await seed_knowledge(env, "k", project="acme")
    n = await seed_knowledge(env, "n", status=ACCEPTED)
    old = await seed_knowledge(env, "old", status=ACCEPTED)
    evidence = await seed_experience(env, "ev")
    log: list[tuple[set[str], set[str]]] = []

    proposed = await env.propose_assertion(tracing(env, log)).handle(
        propose_command(SUPPORTS, subject, object_, "pa")
    )
    await env.accept_knowledge(tracing(env, log)).handle(accept_knowledge_command(k, "ak"))
    sup = await env.propose_assertion().handle(
        propose_command(SUPERSEDES, n, old, "ps", evidence=(evidence,))
    )
    # Propose and accept-knowledge each commit one record together with its own entry.
    assert log == [({proposed.id}, {proposed.id}), ({k.value}, {k.value})]
    log.clear()
    await env.accept_assertion(tracing(env, log)).handle(
        accept_assertion_command(RecordId(value=sup.id), "as", actor=USER)
    )

    # S's accept and O's supersede effect each commit one record together with its own entry.
    assert log == [({sup.id}, {sup.id}), ({old.value}, {old.value})]
    assert proposed.id in {c.record_id for c in env.store.changes}


@pytest.mark.parametrize("command", ["propose", "accept-knowledge", "retract-knowledge"])
async def test_ac019_change_feed_nothing_is_recorded_when_the_unit_does_not_commit_unit(
    command: str,
) -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "s", status=ACCEPTED)
    object_ = await seed_knowledge(env, "o", status=ACCEPTED)
    k = await seed_knowledge(env, "k", project="acme")
    mark = len(env.store.changes)
    factory = RecordingUowFactory(env.store, fail_on_commit=1)

    with pytest.raises(GraphStoreUnavailableError):
        match command:
            case "propose":
                await env.propose_assertion(factory).handle(
                    propose_command(SUPPORTS, subject, object_, "pa")
                )
            case "accept-knowledge":
                await env.accept_knowledge(factory).handle(accept_knowledge_command(k, "ak"))
            case _:
                await env.retract_knowledge(factory).handle(retract_knowledge_command(k, "r"))

    assert feed_after(env, mark) == []
    assert env.store.knowledge[k.value].status is PROPOSED
