"""`noesis assertion|review` as real child processes against the pinned Neo4j container.

Cross-process level of the done-when scenarios of C4: AC-001, AC-002, AC-003 (pty), AC-004 (pty),
AC-005, AC-007 (race), AC-011, AC-013, AC-015, AC-022 (pty), AC-026 (pty), AC-027/AC-023/AC-028
(container parts), AC-030 (pty), the races and the edge cases of 90-verification. The closed-port
cases live in `test_review_outage.py`. Seeding goes through the handlers in-process
(`tests/support/review_support.py`); the commands under test are always separate processes whose
actor comes only from the markers in the environment `env_agent` / `env_user` build. Commands that
need the user's terminal run with `tty=True` (a pty) and are skipped off Linux and macOS.

Race tests run `RACE_PAIRS` pairs (20, as 90-verification) and start both children before
awaiting either.
"""

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.knowledge_neo4j_support import query
from tests.support.noesis_process_support import (
    ProcessResult,
    finish,
    run_noesis,
    start_noesis,
    store_environment,
)
from tests.support.review_commands import accept_assertion_command
from tests.support.review_support import (
    AGENT_SESSION,
    MIGRATED,
    CommitFailingFactory,
    ReviewNeo4jEnv,
    count_nodes,
    decisions_of,
    env_agent,
    env_user,
    graph_digest,
    record_snapshot,
    requires_pty,
    run_with_handlers,
    stored_status,
)

from noesis.bounded_context.knowledge.domain.value_objects import AssertionPredicateEnum
from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SPACE = "default"
RACE_PAIRS = 20
SUPPORTS = AssertionPredicateEnum.SUPPORTS
SUPERSEDES = AssertionPredicateEnum.SUPERSEDES


@pytest.fixture
def env(tmp_path: Path, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """Child environment for the wiped container, space `default` (not a git repository: no --project fallback)."""
    return store_environment(tmp_path / "child-home", SPACE, neo4j_settings)


@pytest.fixture
def initialised(env: dict[str, str]) -> dict[str, str]:
    """`env` after `store init` ran in its own process (real step registry, `review` included)."""
    assert run_noesis(["store", "init"], env).code == 0
    return env


# --- command lines ------------------------------------------------------------------------------


def _capture(
    key: str,
    *,
    project: str | None = "acme",
    tags: tuple[str, ...] = (),
    title: str = "Retry policy",
) -> list[str]:
    argv = [
        "record",
        "capture",
        "--type",
        "knowledge",
        "--title",
        title,
        "--body",
        "Use retries.",
        "--subtype",
        "decision",
        "--source",
        "commit:" + "a" * 40,
        "--idempotency-key",
        key,
    ]
    if project:
        argv += ["--project", project]
    for tag in tags:
        argv += ["--tag", tag]
    return argv


def _accept(record_id: str, key: str, *, expected: int | None = 1) -> list[str]:
    argv = ["review", "accept", record_id, "--yes", "--idempotency-key", key]
    return [*argv, "--expected-revision", str(expected)] if expected is not None else argv


def _retract(record_id: str, key: str, reason: str = "race") -> list[str]:
    return ["review", "retract", record_id, "--reason", reason, "--yes", "--idempotency-key", key]


def _propose(
    predicate: str,
    subject: str,
    object_: str,
    key: str,
    *,
    project: str | None = "acme",
    evidence: tuple[str, ...] = (),
) -> list[str]:
    argv = [
        "assertion",
        "propose",
        "--predicate",
        predicate,
        "--subject",
        subject,
        "--object",
        object_,
        "--rationale",
        "because",
        "--source",
        "agent_session:s1",
        "--idempotency-key",
        key,
    ]
    if project:
        argv += ["--project", project]
    for item in evidence:
        argv += ["--evidence", item]
    return argv


BULK_ALL = ["review", "accept", "--tag", MIGRATED, "--all"]


# --- helpers ------------------------------------------------------------------------------------


def _seed[T](settings: Neo4jConnectionSettings, use: Callable[[ReviewNeo4jEnv], Awaitable[T]]) -> T:
    return run_with_handlers(settings, use)


def _race(
    env: dict[str, str], first: list[str], second: list[str], *, tty: bool = False
) -> tuple[ProcessResult, ProcessResult]:
    """Start both commands before awaiting either, so they overlap."""
    started = time.monotonic()
    one = start_noesis(first, env, tty=tty)
    two = start_noesis(second, env, tty=tty)
    return finish(one, started), finish(two, started)


def _log(env: dict[str, str], record_id: str) -> list[dict[str, Any]]:
    result = run_noesis(["review", "log", record_id], env_agent(env))
    assert result.code == 0, (result.stdout, result.stderr)
    return result.result["decisions"]  # type: ignore[return-value]


def _get(env: dict[str, str], record_id: str) -> dict[str, Any]:
    result = run_noesis(["record", "get", record_id], env_agent(env))
    assert result.code == 0, (result.stdout, result.stderr)
    return result.result


def _id(result: ProcessResult, field: str = "record_id") -> str:
    assert result.code == 0, (result.stdout, result.stderr)
    return str(result.result[field])


def _effects(result: ProcessResult) -> list[tuple[str, str]]:
    return [(e["record_id"], e["outcome"]) for e in result.result["effects"]]  # type: ignore[union-attr]


# --- AC-001, AC-002, AC-003 ---------------------------------------------------------------------


def test_ac001_agent_accepts_project_knowledge(initialised: dict[str, str]) -> None:
    agent = env_agent(initialised)
    record = _id(run_noesis(_capture("cap-1"), agent))

    accepted = run_noesis(_accept(record, "ac001"), agent)

    assert accepted.code == 0, (accepted.stdout, accepted.stderr)
    result = accepted.result
    assert (result["status"], result["pinned_revision"], result["decision_seq"]) == (
        "accepted",
        1,
        1,
    )
    assert (result["basis"], result["applied"]) == ("agent_project", True)
    (decision,) = _log(initialised, record)
    assert (decision["seq"], decision["transition"]) == (1, "accept")
    assert (decision["from_status"], decision["to_status"]) == ("proposed", "accepted")
    assert decision["actor"]["kind"] == "agent"
    assert decision["actor"]["session"] == AGENT_SESSION
    assert decision["pinned_revision"] == 1
    fetched = _get(initialised, record)
    assert (fetched["status"], fetched["effective_status"]) == ("accepted", "accepted")
    assert fetched["superseded_by"] is None
    assert "accepted_revision" not in fetched and "drifted" not in fetched


def test_ac002_agent_cannot_accept_global(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    agent = env_agent(initialised)
    record = _id(run_noesis(_capture("cap-g", project=None), agent))
    digest = graph_digest(neo4j_settings)

    refused = run_noesis(_accept(record, "ac002"), agent)

    assert refused.code == 1
    assert refused.error["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert refused.error["next_steps"]
    assert _get(initialised, record)["status"] == "proposed"
    assert _log(initialised, record) == []
    assert graph_digest(neo4j_settings) == digest
    queue = run_noesis(["review", "queue", "--global"], agent).result["items"]
    (item,) = [i for i in queue if i["id"] == record]  # type: ignore[union-attr]
    assert (item["requires"], item["decidable_by_caller"]) == ("user", False)


@requires_pty
def test_ac003_user_accepts_global(initialised: dict[str, str]) -> None:
    record = _id(run_noesis(_capture("cap-g", project=None), env_agent(initialised)))

    accepted = run_noesis(_accept(record, "ac003"), env_user(initialised), tty=True)

    assert accepted.code == 0, (accepted.stdout, accepted.stderr)
    assert (accepted.result["status"], accepted.result["basis"]) == ("accepted", "user")
    (decision,) = _log(initialised, record)
    assert decision["actor"]["kind"] == "user" and decision["actor"]["session"] is None


# --- AC-004, AC-005, reverse and late supersession ----------------------------------------------


@requires_pty
def test_ac004_accepted_supersedes_marks_object(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    new, old = _seed(
        neo4j_settings,
        lambda e: _two_accepted(e),
    )
    proposed = run_noesis(
        _propose("supersedes", new, old, "p4", project=None), env_agent(initialised)
    )
    supersedes = _id(proposed, "id")

    accepted = run_noesis(
        _accept(supersedes, "ac004", expected=None), env_user(initialised), tty=True
    )

    assert accepted.code == 0, (accepted.stdout, accepted.stderr)
    assert _effects(accepted) == [(old, "applied")]
    old_record = _get(initialised, old)
    assert (old_record["status"], old_record["effective_status"]) == ("superseded", "superseded")
    assert old_record["superseded_by"] == {"assertion_id": supersedes, "record_id": new}
    assert old_record["revision"]["title"] == "Old rule"
    assert old_record["revision"]["body"] == "Use retries."
    last = _log(initialised, old)[-1]
    assert (last["transition"], last["from_status"], last["to_status"]) == (
        "supersede",
        "accepted",
        "superseded",
    )
    assert last["cause_assertion_id"] == supersedes and last["basis"] == "supersession_effect"
    assert _get(initialised, new)["status"] == "accepted"


async def _two_accepted(e: ReviewNeo4jEnv) -> tuple[str, str]:
    new = await e.seed_accepted("n", title="New rule")
    old = await e.seed_accepted("o", title="Old rule")
    return new.value, old.value


def test_ac005_agent_cannot_supersede_global_and_may_within_a_project(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    settings = neo4j_settings

    async def seed(e: ReviewNeo4jEnv) -> dict[str, str]:
        evidence = (await e.capture_experience()).value
        return {
            "n": (await e.seed_accepted("n")).value,
            "o": (await e.seed_accepted("o")).value,
            "pn": (await e.seed_accepted("pn", project="acme")).value,
            "po": (await e.seed_accepted("po", project="acme")).value,
            "e": evidence,
        }

    ids = _seed(settings, seed)
    agent = env_agent(initialised)
    global_s = _id(
        run_noesis(
            _propose("supersedes", ids["n"], ids["o"], "g", project=None, evidence=(ids["e"],)),
            agent,
        ),
        "id",
    )
    scoped_s = _id(
        run_noesis(_propose("supersedes", ids["pn"], ids["po"], "s", evidence=(ids["e"],)), agent),
        "id",
    )

    refused = run_noesis(_accept(global_s, "ac005", expected=None), agent)
    control = run_noesis(_accept(scoped_s, "ac005-ok", expected=None), agent)

    assert refused.code == 1
    assert refused.error["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert _get(initialised, global_s)["status"] == "proposed"
    old = _get(initialised, ids["o"])
    assert (old["status"], old["effective_status"]) == ("accepted", "accepted")
    assert _log(initialised, global_s) == []
    assert [d["transition"] for d in _log(initialised, ids["o"])] == ["accept"]
    assert control.code == 0, (control.stdout, control.stderr)
    assert _effects(control) == [(ids["po"], "applied")]


@requires_pty
def test_reverse_supersession_cannot_be_accepted(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    settings = neo4j_settings

    async def seed(e: ReviewNeo4jEnv) -> tuple[str, str]:
        new = await e.seed_accepted("n")
        old = await e.seed_accepted("o")
        await e.seed_accepted_assertion(SUPERSEDES, new, old, "forward")
        return new.value, old.value

    new, old = _seed(settings, seed)
    reverse = _id(
        run_noesis(
            _propose("supersedes", old, new, "reverse", project=None), env_agent(initialised)
        ),
        "id",
    )

    refused = run_noesis(_accept(reverse, "rev", expected=None), env_user(initialised), tty=True)

    assert refused.code == 1
    assert refused.error["code"] == "KNOWLEDGE_222_REFERENCE_NOT_ACCEPTABLE"
    assert _get(initialised, new)["status"] == "accepted"


@requires_pty
def test_ac022_supersedes_with_proposed_subject(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    settings = neo4j_settings

    async def seed(e: ReviewNeo4jEnv) -> tuple[str, str]:
        return (await e.seed_accepted("o")).value, (await e.capture("n")).value

    old, new = _seed(settings, seed)
    user = env_user(initialised)

    proposed = run_noesis(
        _propose("supersedes", new, old, "p22", project=None), env_agent(initialised)
    )
    supersedes = _id(proposed, "id")
    early = run_noesis(_accept(supersedes, "ac022-s", expected=None), user, tty=True)
    accepted_subject = run_noesis(_accept(new, "ac022-n"), user, tty=True)
    late = run_noesis(_accept(supersedes, "ac022-s2", expected=None), user, tty=True)

    assert (
        proposed.result["status"] == "proposed" and proposed.result["subject"]["at_revision"] == 1
    )  # type: ignore[index]
    assert early.code == 1
    assert early.error["code"] == "KNOWLEDGE_222_REFERENCE_NOT_ACCEPTABLE"
    assert accepted_subject.code == 0, (accepted_subject.stdout, accepted_subject.stderr)
    assert late.code == 0, (late.stdout, late.stderr)
    assert _effects(late) == [(old, "applied")]
    assert [d["transition"] for d in _log(initialised, old)] == ["accept", "supersede"]


# --- AC-011, AC-013 -----------------------------------------------------------------------------


def test_ac011_accepted_graph_owned_not_revisable(initialised: dict[str, str]) -> None:
    agent = env_agent(initialised)
    record = _id(run_noesis(_capture("cap-1"), agent))
    assert run_noesis(_accept(record, "acc"), agent).code == 0

    revise = run_noesis(
        [
            "record",
            "revise",
            record,
            "--expected-revision",
            "1",
            "--title",
            "x",
            "--idempotency-key",
            "r1",
        ],
        agent,
    )

    assert revise.code == 1
    assert revise.error["code"] == "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE"
    fetched = _get(initialised, record)
    assert (fetched["head_revision"], fetched["status"]) == (1, "accepted")
    assert fetched["revision"]["title"] == "Retry policy"


@requires_pty
def test_ac013_agent_needs_evidence(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    settings = neo4j_settings

    async def seed(e: ReviewNeo4jEnv) -> tuple[str, str]:
        return (
            (await e.seed_accepted("k", project="acme")).value,
            (await e.capture("k2", project="acme")).value,
        )

    accepted, proposed = _seed(settings, seed)
    agent = env_agent(initialised)
    assertion = _id(
        run_noesis(_propose("supports", proposed, accepted, "no-evidence"), agent), "id"
    )

    refused = run_noesis(_accept(assertion, "ac013", expected=None), agent)
    as_user = run_noesis(
        _accept(assertion, "ac013-user", expected=None), env_user(initialised), tty=True
    )

    assert refused.code == 1
    assert refused.error["code"] == "KNOWLEDGE_023_EVIDENCE_REQUIRED"
    assert as_user.code == 0, (as_user.stdout, as_user.stderr)
    assert _get(initialised, assertion)["status"] == "accepted"


# --- AC-015 -------------------------------------------------------------------------------------


def test_ac015_accept_replay_by_key(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    agent = env_agent(initialised)
    record = _id(run_noesis(_capture("cap-1"), agent))

    first, second = _race(agent, _accept(record, "same"), _accept(record, "same"))
    different = run_noesis([*_accept(record, "same"), "--reason", "other"], agent)

    assert (first.code, second.code) == (0, 0), [
        (first.stdout, first.stderr),
        (second.stdout, second.stderr),
    ]
    drop = {"replayed"}
    assert {k: v for k, v in first.result.items() if k not in drop} == {
        k: v for k, v in second.result.items() if k not in drop
    }
    assert len(_log(initialised, record)) == 1
    assert different.code == 1
    assert different.error["code"] == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"
    experience = _seed(neo4j_settings, lambda e: e.capture_experience())
    request = _propose("supports", experience.value, record, "prop-same")
    one = run_noesis(request, agent)
    again = run_noesis(request, agent)
    assert one.code == again.code == 0
    assert one.result["id"] == again.result["id"]
    assert count_nodes(neo4j_settings, "Assertion") == 1


# --- races (NFR-003) ----------------------------------------------------------------------------


async def _capture_many(e: ReviewNeo4jEnv, count: int, *, tags: tuple[str, ...] = ()) -> list[str]:
    return [(await e.capture(f"race-{n}", project="acme", tags=tags)).value for n in range(count)]


def test_ac007_accept_retract_race(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    """One decision per sequence number; the loser of an overlap is 220, or 021 when it started late.

    A retract that starts after the accept committed is itself legal (accepted to retracted), so
    that interleaving ends with two decisions, never with a duplicated sequence number.
    """
    records = _seed(neo4j_settings, lambda e: _capture_many(e, RACE_PAIRS))
    agent = env_agent(initialised)

    for index, record in enumerate(records):
        accepted, retracted = _race(
            agent, _accept(record, f"a-{index}"), _retract(record, f"r-{index}")
        )

        decisions = _log(initialised, record)
        assert len({d["seq"] for d in decisions}) == len(decisions)
        if accepted.code == retracted.code == 0:
            assert [d["transition"] for d in decisions] == ["accept", "retract"]
            continue
        loser = retracted if accepted.code == 0 else accepted
        assert {accepted.code, retracted.code} == {0, 1}, (accepted.stdout, retracted.stdout)
        assert loser.error["code"] in {
            "KNOWLEDGE_220_STATUS_CONFLICT",
            "KNOWLEDGE_021_INVALID_STATUS_TRANSITION",
        }
        assert len(decisions) == 1


def test_revise_against_accept_commits_exactly_one(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    records = _seed(neo4j_settings, lambda e: _capture_many(e, RACE_PAIRS))
    agent = env_agent(initialised)

    for index, record in enumerate(records):
        revise = [
            "record",
            "revise",
            record,
            "--expected-revision",
            "1",
            "--body",
            "Revised.",
            "--idempotency-key",
            f"rv-{index}",
        ]
        revised, accepted = _race(agent, revise, _accept(record, f"a-{index}"))

        assert {revised.code, accepted.code} == {0, 1}, (revised.stdout, accepted.stdout)
        fetched = _get(initialised, record)
        if accepted.code == 0:
            assert revised.error["code"] == "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE"
            (decision,) = _log(initialised, record)
            assert decision["pinned_revision"] == fetched["head_revision"] == 1
        else:
            assert accepted.error["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
            assert fetched["head_revision"] == 2 and fetched["status"] == "proposed"
            assert _log(initialised, record) == []


def test_two_accepts_with_different_keys_commit_one_decision(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    records = _seed(neo4j_settings, lambda e: _capture_many(e, RACE_PAIRS))
    agent = env_agent(initialised)

    for index, record in enumerate(records):
        first, second = _race(agent, _accept(record, f"x-{index}"), _accept(record, f"y-{index}"))

        assert sorted([first.code, second.code]) == [0, 1], (first.stdout, second.stdout)
        loser = first if first.code else second
        assert loser.error["code"] in {
            "KNOWLEDGE_220_STATUS_CONFLICT",
            "KNOWLEDGE_021_INVALID_STATUS_TRANSITION",
        }
        assert len(_log(initialised, record)) == 1


def test_concurrent_identical_proposals_leave_one_live_assertion(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    agent = env_agent(initialised)

    async def seed(e: ReviewNeo4jEnv) -> list[tuple[str, str]]:
        experience = (await e.capture_experience()).value
        return [
            (experience, (await e.seed_accepted(f"k{n}", project="acme")).value) for n in range(3)
        ]

    for index, (experience, record) in enumerate(_seed(neo4j_settings, seed)):
        first, second = _race(
            agent,
            _propose("supports", experience, record, f"x1-{index}"),
            _propose("supports", experience, record, f"x2-{index}"),
        )

        assert sorted([first.code, second.code]) == [0, 1], (first.stdout, second.stdout)
        loser = first if first.code else second
        assert loser.error["code"] == "KNOWLEDGE_221_DUPLICATE_ASSERTION"
        live = query(
            neo4j_settings,
            "MATCH (a:Assertion)-[:OBJECT]->(:Record {id: $id}) "
            "RETURN count(a) AS total, count(a.live_key) AS live",
            id=record,
        )
        assert live == [{"total": 1, "live": 1}]


def test_concurrent_repairs_apply_the_pending_effect_once(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    async def seed(e: ReviewNeo4jEnv) -> str:
        evidence = await e.capture_experience()
        new = await e.seed_accepted("n", project="acme")
        old = await e.seed_accepted("o", project="acme")
        supersedes = await e.propose(
            SUPERSEDES, new, old, "s", project="acme", evidence=(evidence,)
        )
        with pytest.raises(GraphStoreUnavailableError):  # crash between the two units of work
            await e.accept_assertion(CommitFailingFactory(e.uow, fail_on=2)).handle(
                accept_assertion_command(supersedes, "crash")
            )
        return old.value

    old = _seed(neo4j_settings, seed)
    agent = env_agent(initialised)

    first, second = _race(agent, ["review", "repair", "--yes"], ["review", "repair", "--yes"])

    assert (first.code, second.code) == (0, 0), (first.stdout, second.stdout)
    outcomes = [e["outcome"] for r in (first, second) for e in r.result["effects"]]  # type: ignore[union-attr]
    assert outcomes.count("applied") >= 1  # the loser may report applied, skipped or nothing
    assert set(outcomes) <= {"applied", "skipped"}
    assert [d["transition"] for d in _log(initialised, old)] == ["accept", "supersede"]
    assert stored_status(neo4j_settings, old) == "superseded"


# --- retracted record readable ------------------------------------------------------------------


@requires_pty
def test_a_retracted_record_stays_readable_with_its_history(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    record = _seed(neo4j_settings, lambda e: e.seed_accepted("k", project="acme")).value

    retracted = run_noesis(_retract(record, "ret", "obsolete"), env_user(initialised), tty=True)

    assert retracted.code == 0, (retracted.stdout, retracted.stderr)
    assert retracted.result["outcome"] == "retracted"
    fetched = _get(initialised, record)
    assert fetched["status"] == "retracted"
    assert (fetched["revision"]["title"], fetched["revision"]["body"]) == (
        "Retry policy",
        "Use retries.",
    )
    assert [d["transition"] for d in _log(initialised, record)] == ["accept", "retract"]


# --- bulk accept ---------------------------------------------------------------------------------


@requires_pty
@pytest.mark.parametrize("reason", [None, "vault import reviewed"])
def test_ac026_bulk_accept_as_user(
    initialised: dict[str, str], reason: str | None, neo4j_settings: Neo4jConnectionSettings
) -> None:
    fixture = _seed(neo4j_settings, lambda e: e.seed_bulk_fixture())
    argv = [*BULK_ALL, "--yes"] + (["--reason", reason] if reason else [])

    applied = run_noesis(argv, env_user(initialised), tty=True)

    assert applied.code == 0, (applied.stdout, applied.stderr)
    result = applied.result
    assert result["applied"] is True
    assert (result["matched"], result["proposed"], result["accepted"]) == (3, 2, 2)
    assert (result["skipped_not_proposed"], result["skipped_changed"]) == (1, 0)
    assert [i["id"] for i in result["sample"]] == sorted([fixture.k1.value, fixture.k2.value])  # type: ignore[union-attr]
    expected_reason = reason or f"bulk accept: tag {MIGRATED}"
    for record, pinned in ((fixture.k1, 2), (fixture.k2, 1)):
        (decision,) = _log(initialised, record.value)
        assert (decision["seq"], decision["transition"]) == (1, "accept")
        assert (decision["from_status"], decision["to_status"]) == ("proposed", "accepted")
        assert decision["actor"]["kind"] == "user" and decision["actor"]["session"] is None
        assert (decision["basis"], decision["pinned_revision"]) == ("migration", pinned)
        assert decision["reason"] == expected_reason
        assert _get(initialised, record.value)["status"] == "accepted"
    assert [d["basis"] for d in _log(initialised, fixture.k3.value)] == ["user"]
    assert _get(initialised, fixture.k5.value)["status"] == "proposed"
    assert _log(initialised, fixture.k5.value) == []


def test_ac025_preview_from_a_process_as_agent_and_user_writes_nothing(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    fixture = _seed(neo4j_settings, lambda e: e.seed_bulk_fixture())
    digest = graph_digest(neo4j_settings)

    for env in (env_agent(initialised), env_user(initialised)):
        preview = run_noesis(BULK_ALL, env)

        assert preview.code == 0, (preview.stdout, preview.stderr)
        result = preview.result
        assert result["applied"] is False and result["basis"] == "migration"
        assert (result["matched"], result["proposed"], result["skipped_not_proposed"]) == (3, 2, 1)
        assert (result["accepted"], result["skipped_changed"]) == (0, 0)
        assert [i["id"] for i in result["sample"]] == sorted([fixture.k1.value, fixture.k2.value])  # type: ignore[union-attr]
        assert graph_digest(neo4j_settings) == digest


def test_ac027_bulk_accept_refused_for_agent_against_the_container(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    _seed(neo4j_settings, lambda e: e.seed_bulk_fixture())
    digest = graph_digest(neo4j_settings)

    refused = run_noesis([*BULK_ALL, "--yes"], env_agent(initialised))

    assert refused.code == 1
    assert refused.error["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert refused.error["metadata"]["reason"] == "bulk_accept_requires_user"  # type: ignore[index]
    assert refused.error["next_steps"]
    assert graph_digest(neo4j_settings) == digest


def test_ac028_ac023_the_user_without_a_terminal_is_refused_against_the_container(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    fixture = _seed(neo4j_settings, lambda e: e.seed_bulk_fixture())
    digest = graph_digest(neo4j_settings)
    user = env_user(initialised)

    for argv in (
        [*BULK_ALL, "--yes"],
        _accept(fixture.k5.value, "no-tty"),
        _retract(fixture.k5.value, "no-tty", "x"),
    ):
        refused = run_noesis(argv, user)

        assert refused.code == 1, argv
        assert refused.error["code"] == "INTERFACE_006_USER_PRESENCE_REQUIRED", argv
        assert graph_digest(neo4j_settings) == digest


@requires_pty
def test_ac030_bulk_accept_touches_only_tagged_proposed_knowledge(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    world = _seed(neo4j_settings, lambda e: e.seed_selection_world())
    before = {r.value: record_snapshot(neo4j_settings, r.value) for r in world.untouched}

    applied = run_noesis([*BULK_ALL, "--yes"], env_user(initialised), tty=True)

    assert applied.code == 0, (applied.stdout, applied.stderr)
    result = applied.result
    assert (result["matched"], result["proposed"], result["accepted"]) == (3, 1, 1)
    assert result["skipped_not_proposed"] == 2
    assert [
        r.value
        for r in world.untouched
        if record_snapshot(neo4j_settings, r.value) != before[r.value]
    ] == []
    assert _get(initialised, world.k1.value)["status"] == "accepted"
    assert [d["basis"] for d in decisions_of(neo4j_settings, world.k1.value)] == ["migration"]


@requires_pty
def test_concurrent_bulk_accepts_decide_every_record_once(
    initialised: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    records = _seed(neo4j_settings, lambda e: _capture_many(e, 50, tags=(MIGRATED,)))

    first, second = _race(
        env_user(initialised), [*BULK_ALL, "--yes"], [*BULK_ALL, "--yes"], tty=True
    )

    assert (first.code, second.code) == (0, 0), [
        (first.stdout, first.stderr),
        (second.stdout, second.stderr),
    ]
    assert first.result["accepted"] + second.result["accepted"] == 50  # type: ignore[operator]
    for run in (first, second):
        # a record accepted by the other run before this run read its page is simply not listed
        assert run.result["accepted"] + run.result["skipped_changed"] <= run.result["proposed"]  # type: ignore[operator]
        assert run.result["matched"] == 50
    for record in records:
        assert [d["seq"] for d in decisions_of(neo4j_settings, record)] == [1]
        assert stored_status(neo4j_settings, record) == "accepted"
