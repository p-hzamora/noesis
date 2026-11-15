"""`assertion` and `review` against the pinned Neo4j container, in-process.

Covers AC-008, AC-009 (CLI), AC-010 (CLI), AC-025 (preview variants), the error rows
`KNOWLEDGE_224/201/021/223/022`, previews that write nothing, `assertion list` filters, `record get`
of an assertion and the Knowledge additions, and the shape of `review log` and `review queue`.
Seeding goes through the handlers (`tests/support/review_support.py`); the commands under test run
through the Typer entry point with the actor taken from the environment, as in production.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from tests.support.knowledge_cli_support import run_json, use_store
from tests.support.knowledge_neo4j_support import query
from tests.support.knowledge_support import AGENT
from tests.support.review_support import (
    AGENT_SESSION,
    MIGRATED,
    ReviewNeo4jEnv,
    attach_terminal,
    graph_digest,
    run_with_handlers,
)

from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    Key,
    RecordId,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SUPPORTS = AssertionPredicateEnum.SUPPORTS
RECOMMENDS = AssertionPredicateEnum.RECOMMENDS
MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.fixture
def store(
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Neo4jConnectionSettings:
    """An initialised database (all registered steps) in space `default`, the CLI configured for it."""
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("NOESIS_KNOWLEDGE_SPACE", "default")
    code, _ = run_json(capsys, ["store", "init"])
    assert code == 0
    return neo4j_settings


def _seed[T](settings: Neo4jConnectionSettings, use: Callable[[ReviewNeo4jEnv], Awaitable[T]]) -> T:
    return run_with_handlers(settings, use)


def _agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", AGENT_SESSION)


def _user(monkeypatch: pytest.MonkeyPatch, *, tty: bool = True) -> None:
    monkeypatch.delenv("NOESIS_SESSION_ID", raising=False)
    attach_terminal(monkeypatch, tty=tty)


def _result(envelope: dict[str, object]) -> dict[str, Any]:
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


def _error(envelope: dict[str, object]) -> dict[str, Any]:
    assert envelope["ok"] is False, envelope
    error = envelope["error"]
    assert isinstance(error, dict)
    return error


def _accept(record_id: RecordId | str, key: str = "a1", *, expected: int | None = 1) -> list[str]:
    argv = ["review", "accept", str(getattr(record_id, "value", record_id)), "--yes"]
    argv += ["--idempotency-key", key]
    return [*argv, "--expected-revision", str(expected)] if expected is not None else argv


def _retract(
    record_id: RecordId | str, key: str = "r1", reason: str = "no longer true"
) -> list[str]:
    value = str(getattr(record_id, "value", record_id))
    return ["review", "retract", value, "--reason", reason, "--yes", "--idempotency-key", key]


def _propose(
    predicate: str,
    subject: RecordId,
    object_: RecordId,
    key: str,
    *,
    project: str | None = "acme",
    evidence: tuple[RecordId, ...] = (),
    rationale: str = "because",
) -> list[str]:
    argv = [
        "assertion",
        "propose",
        "--predicate",
        predicate,
        "--subject",
        subject.value,
        "--object",
        object_.value,
        "--rationale",
        rationale,
        "--source",
        "agent_session:s1",
        "--idempotency-key",
        key,
    ]
    if project:
        argv += ["--project", project]
    for item in evidence:
        argv += ["--evidence", item.value]
    return argv


def _log(capsys: pytest.CaptureFixture[str], record_id: RecordId) -> list[dict[str, Any]]:
    code, envelope = run_json(capsys, ["review", "log", record_id.value])
    assert code == 0
    return _result(envelope)["decisions"]


# --- AC-008, AC-009, AC-010 ---------------------------------------------------------------------


def test_ac008_stale_expected_revision(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _seed(store, lambda e: e.capture("k", project="acme"))
    _agent(monkeypatch)
    revise = ["record", "revise", record.value, "--expected-revision", "1", "--body", "Newer."]
    assert run_json(capsys, [*revise, "--idempotency-key", "r1"])[0] == 0

    code, envelope = run_json(capsys, _accept(record, "a1", expected=1))

    error = _error(envelope)
    assert code == 1
    assert error["code"] == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert error["metadata"]["expected_revision"] == 1
    assert error["metadata"]["actual_revision"] == 2
    assert _log(capsys, record) == []
    _, fetched = run_json(capsys, ["record", "get", record.value])
    assert _result(fetched)["status"] == "proposed"


def test_ac009_creation_invariants_cli(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record, evidence = _seed(store, _pair)
    _agent(monkeypatch)
    digest = graph_digest(store)

    code, envelope = run_json(capsys, _propose("supports", record, record, "same-key"))

    assert code == 1
    assert _error(envelope)["code"] == "KNOWLEDGE_020_INVALID_ASSERTION"
    assert graph_digest(store) == digest
    code, envelope = run_json(capsys, _propose("supports", evidence, record, "same-key"))
    proposed = _result(envelope)
    assert code == 0
    assert proposed["status"] == "proposed"
    assert proposed["predicate"] == "supports"
    assert proposed["subject"] == {"id": evidence.value, "at_revision": None}
    assert proposed["object"] == {"id": record.value, "at_revision": 1}
    assert proposed["applicability"]["project_key"] == "acme"


async def _pair(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId]:
    """Accepted knowledge `K` in acme and an experience `E`."""
    return await env.seed_accepted("k", project="acme"), await env.capture_experience()


def test_ac010_duplicate_live_statement(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    k, e = _seed(store, _pair)
    _agent(monkeypatch)
    _, first = run_json(capsys, _propose("supports", e, k, "k1"))
    first_id = _result(first)["id"]

    code, duplicate = run_json(capsys, _propose("supports", e, k, "k2"))
    other_code, other_project = run_json(capsys, _propose("supports", e, k, "k4", project="other"))
    retract_code, retracted = run_json(capsys, _retract(first_id, "ret-1", "dup"))
    again_code, again = run_json(capsys, _propose("supports", e, k, "k3"))

    assert code == 1
    error = _error(duplicate)
    assert error["code"] == "KNOWLEDGE_221_DUPLICATE_ASSERTION"
    assert first_id in str(error["metadata"])
    assert other_code == 0  # the project is part of the statement
    assert _result(other_project)["id"] != first_id
    assert retract_code == 0 and _result(retracted)["outcome"] == "rejected"
    assert again_code == 0
    second = _result(again)
    assert second["id"] != first_id and second["status"] == "proposed"
    live = {
        row["id"]: row["live_key"]
        for row in query(store, "MATCH (a:Assertion) RETURN a.id AS id, a.live_key AS live_key")
    }
    assert live[first_id] is None
    assert live[second["id"]]


# --- AC-025 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("actor", ["agent", "user"])
def test_ac025_bulk_accept_preview(
    actor: str,
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _seed(store, lambda e: e.seed_bulk_fixture())
    if actor == "agent":
        _agent(monkeypatch)
    else:
        _user(monkeypatch, tty=False)
    digest = graph_digest(store)

    code, envelope = run_json(capsys, ["review", "accept", "--tag", MIGRATED, "--all"])

    result = _result(envelope)
    assert code == 0
    assert result["applied"] is False and result["tag"] == MIGRATED
    assert (result["matched"], result["proposed"], result["skipped_not_proposed"]) == (3, 2, 1)
    assert (result["accepted"], result["skipped_changed"], result["basis"]) == (0, 0, "migration")
    ordered = sorted([fixture.k1.value, fixture.k2.value])
    assert [item["id"] for item in result["sample"]] == ordered
    by_id = {item["id"]: item for item in result["sample"]}
    assert by_id[fixture.k1.value]["project_key"] == "acme"
    assert by_id[fixture.k1.value]["head_revision"] == 2
    assert by_id[fixture.k1.value]["title"] == "Bulk one"
    assert by_id[fixture.k1.value]["subtype"] == "decision"
    assert by_id[fixture.k2.value]["project_key"] is None
    assert by_id[fixture.k2.value]["head_revision"] == 1
    assert by_id[fixture.k2.value]["title"] == "Bulk two"
    assert graph_digest(store) == digest


def test_ac025_preview_sample_is_the_ten_lowest_ids_of_twelve(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def twelve(env: ReviewNeo4jEnv) -> list[str]:
        return [(await env.capture(f"t{n:02}", tags=(MIGRATED,))).value for n in range(12)]

    ids = _seed(store, twelve)
    _agent(monkeypatch)

    code, envelope = run_json(capsys, ["review", "accept", "--tag", MIGRATED, "--all"])

    result = _result(envelope)
    assert code == 0 and result["proposed"] == 12 and result["matched"] == 12
    assert [item["id"] for item in result["sample"]] == sorted(ids)[:10]


def test_ac025_a_tag_nothing_carries_gives_zero_counts_and_exit_0(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(store, lambda e: e.seed_bulk_fixture())
    _agent(monkeypatch)

    code, envelope = run_json(capsys, ["review", "accept", "--tag", "nothing:here", "--all"])

    result = _result(envelope)
    assert code == 0
    assert (result["matched"], result["proposed"], result["skipped_not_proposed"]) == (0, 0, 0)
    assert (result["accepted"], result["skipped_changed"]) == (0, 0)
    assert result["sample"] == []


# --- error rows ---------------------------------------------------------------------------------


def test_transitions_on_non_reviewable_records_are_knowledge_224(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, experience = _seed(store, _pair)
    source_id = query(store, "MATCH (s:Source) RETURN s.id AS id LIMIT 1")[0]["id"]
    _agent(monkeypatch)

    accept_code, accept = run_json(capsys, _accept(experience, "a1", expected=None))
    retract_code, retract = run_json(capsys, _retract(source_id, "r1", "x"))

    assert accept_code == retract_code == 1
    assert (
        _error(accept)["code"] == _error(retract)["code"] == "KNOWLEDGE_224_RECORD_NOT_REVIEWABLE"
    )


def test_an_unknown_id_and_a_record_of_another_space_are_knowledge_201(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
        InitialiseStoreCommand,
    )

    async def foreign(env: ReviewNeo4jEnv) -> RecordId:
        await env.base.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=Key(value="space-b"))
        )
        return await env.capture("kb", project="acme", space_key=Key(value="space-b"))

    in_space_b = _seed(store, foreign)
    _agent(monkeypatch)

    unknown_code, unknown = run_json(capsys, _accept(MISSING_ID))
    foreign_code, other_space = run_json(capsys, _accept(in_space_b))

    assert unknown_code == foreign_code == 1
    assert (
        _error(unknown)["code"] == _error(other_space)["code"] == "KNOWLEDGE_201_RECORD_NOT_FOUND"
    )


def test_accepting_accepted_knowledge_is_knowledge_021_and_adds_no_decision(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _seed(store, lambda e: e.seed_accepted("k", project="acme"))
    _agent(monkeypatch)

    code, envelope = run_json(capsys, _accept(record, "again"))

    assert code == 1
    assert _error(envelope)["code"] == "KNOWLEDGE_021_INVALID_STATUS_TRANSITION"
    assert len(_log(capsys, record)) == 1


def test_expected_revision_is_required_for_knowledge_and_not_for_an_assertion(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId]:
        _, experience = await _pair(env)
        pending = await env.capture("pending", project="acme")
        assertion = await env.propose(
            SUPPORTS, experience, pending, "a", project="acme", evidence=(experience,)
        )
        return pending, assertion

    knowledge, assertion = _seed(store, seed)
    _agent(monkeypatch)

    code, missing = run_json(capsys, _accept(knowledge, "a1", expected=None))
    assertion_code, accepted = run_json(capsys, _accept(assertion, "a2", expected=None))

    assert code == 1
    assert _error(missing)["code"] == "KNOWLEDGE_223_EXPECTED_REVISION_REQUIRED"
    assert assertion_code == 0 and _result(accepted)["status"] == "accepted"
    assert _result(accepted)["pinned_revision"] is None


@pytest.mark.parametrize("stored", ["proposed", "accepted"])
def test_an_agent_may_not_retract_global_guidance(
    stored: str,
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> RecordId:
        if stored == "accepted":
            return await env.seed_accepted("g")
        return await env.capture("g")

    record = _seed(store, seed)
    _agent(monkeypatch)

    code, envelope = run_json(capsys, _retract(record, "r1", "x"))

    assert code == 1
    assert _error(envelope)["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    _, fetched = run_json(capsys, ["record", "get", record.value])
    assert _result(fetched)["status"] == stored


# --- previews write nothing -----------------------------------------------------------------------


def test_previews_report_the_result_and_write_nothing(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId]:
        return await env.capture("scoped", project="acme"), await env.capture("global")

    scoped, global_ = _seed(store, seed)
    _agent(monkeypatch)
    digest = graph_digest(store)

    accept_code, accept = run_json(
        capsys, ["review", "accept", scoped.value, "--expected-revision", "1"]
    )
    retract_code, retract = run_json(capsys, ["review", "retract", scoped.value, "--reason", "x"])
    repair_code, repair = run_json(capsys, ["review", "repair"])
    refused_code, refused = run_json(
        capsys, ["review", "accept", global_.value, "--expected-revision", "1"]
    )

    assert accept_code == retract_code == repair_code == 0
    assert _result(accept)["applied"] is False and _result(accept)["status"] == "accepted"
    assert _result(retract)["applied"] is False and _result(retract)["outcome"] == "rejected"
    assert _result(repair)["applied"] is False and _result(repair)["effects"] == []
    assert refused_code == 1
    assert _error(refused)["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert graph_digest(store) == digest


# --- reads --------------------------------------------------------------------------------------


def test_assertion_list_filters_by_role_predicate_and_status(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId, RecordId, RecordId]:
        k, e = await _pair(env)
        catalog = await env.seed_catalog_entry()
        a1 = await env.propose(SUPPORTS, e, k, "a1", project="acme")
        a2 = await env.propose(RECOMMENDS, k, catalog, "a2", project="acme")
        return k, e, a1, a2

    k, e, a1, a2 = _seed(store, seed)
    _agent(monkeypatch)

    def ids(*options: str) -> list[str]:
        code, envelope = run_json(capsys, ["assertion", "list", "--about", k.value, *options])
        assert code == 0
        return [item["id"] for item in _result(envelope)["assertions"]]

    assert ids("--role", "object") == [a1.value]
    assert ids("--role", "subject") == [a2.value]
    assert ids("--role", "any") == ids() == [a1.value, a2.value]
    assert ids("--predicate", "recommends") == [a2.value]
    assert ids("--status", "retracted") == []
    _, envelope = run_json(capsys, ["assertion", "list", "--about", k.value, "--role", "object"])
    (item,) = _result(envelope)["assertions"]
    assert item["subject"] == {"id": e.value, "at_revision": None, "effective_status": None}
    assert item["object"] == {"id": k.value, "at_revision": 1, "effective_status": "accepted"}
    assert item["status"] == "proposed" and item["effective_status"] == "proposed"
    assert item["predicate"] == "supports"
    assert "evidence" in item and "applicability" in item


def test_record_get_of_an_assertion_returns_every_documented_field(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> tuple[RecordId, RecordId, RecordId]:
        k, e = await _pair(env)
        return k, e, await env.propose(SUPPORTS, e, k, "a1", project="acme", evidence=(e,))

    k, e, assertion = _seed(store, seed)
    _agent(monkeypatch)

    code, envelope = run_json(capsys, ["record", "get", assertion.value])

    record = _result(envelope)
    assert code == 0
    documented = {
        "id",
        "space",
        "predicate",
        "subject",
        "object",
        "evidence",
        "rationale",
        "actor",
        "applicability",
        "status",
        "effective_status",
        "superseded_by",
        "sources",
        "created_at",
    }
    assert documented <= set(record)
    assert record["type"] == "assertion" and record["id"] == assertion.value
    assert (
        record["predicate"] == "supports"
        and record["rationale"] == "Both describe the same retry rule."
    )
    assert record["subject"] == {"id": e.value, "at_revision": None}
    assert record["object"] == {"id": k.value, "at_revision": 1}
    assert record["evidence"] == [e.value]
    assert (record["status"], record["effective_status"], record["superseded_by"]) == (
        "proposed",
        "proposed",
        None,
    )
    assert (
        record["actor"]["kind"] == "agent" and record["actor"]["session"] == AGENT.session
    )  # seeded in-process
    assert len(record["sources"]) == 1


def test_record_get_of_knowledge_adds_effective_status_and_superseded_by_only(
    store: Neo4jConnectionSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _seed(store, lambda e: e.seed_accepted("k", project="acme"))

    _, envelope = run_json(capsys, ["record", "get", record.value])

    result = _result(envelope)
    assert result["status"] == "accepted" and result["effective_status"] == "accepted"
    assert result["superseded_by"] is None
    assert "accepted_revision" not in result and "drifted" not in result
    assert result["head_revision"] == 1


def test_review_log_returns_every_decision_field_ordered_by_seq(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _seed(store, lambda e: e.capture("k", project="acme"))
    _agent(monkeypatch)
    accept_argv = [*_accept(record, "a1"), "--reason", "looks right"]
    assert run_json(capsys, accept_argv)[0] == 0
    _user(monkeypatch)
    assert run_json(capsys, _retract(record, "r1", "obsolete"))[0] == 0

    first, second = _log(capsys, record)

    fields = {
        "seq",
        "transition",
        "from_status",
        "to_status",
        "actor",
        "decided_at",
        "reason",
        "basis",
        "pinned_revision",
        "cause_assertion_id",
    }
    assert fields <= set(first) and fields <= set(second)
    assert (first["seq"], first["transition"], first["basis"]) == (1, "accept", "agent_project")
    assert (first["from_status"], first["to_status"]) == ("proposed", "accepted")
    assert first["actor"]["kind"] == "agent" and first["actor"]["session"] == AGENT_SESSION
    assert first["pinned_revision"] == 1 and first["reason"] == "looks right"
    assert first["cause_assertion_id"] is None
    assert (second["seq"], second["transition"], second["basis"]) == (2, "retract", "user")
    assert (second["from_status"], second["to_status"]) == ("accepted", "retracted")
    assert second["actor"]["kind"] == "user" and second["actor"]["session"] is None
    assert second["reason"] == "obsolete" and second["pinned_revision"] is None


def test_review_queue_lists_what_needs_review_with_who_may_decide(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed(env: ReviewNeo4jEnv) -> dict[str, RecordId]:
        experience = await env.capture_experience()
        scoped = await env.capture("scoped", project="acme")
        global_ = await env.capture("global")
        assertion = await env.propose(
            SUPPORTS, experience, scoped, "a", project="acme", evidence=(experience,)
        )
        return {"scoped": scoped, "global": global_, "assertion": assertion}

    ids = _seed(store, seed)
    _agent(monkeypatch)

    code, envelope = run_json(capsys, ["review", "queue", "--project", "acme"])
    first_code, first_page = run_json(capsys, ["review", "queue", "--limit", "1"])
    cursor = _result(first_page)["next_cursor"]
    second_code, second_page = run_json(
        capsys, ["review", "queue", "--limit", "5", "--cursor", cursor]
    )

    result = _result(envelope)
    assert code == first_code == second_code == 0
    assert result["next_cursor"] is None
    items = {item["id"]: item for item in result["items"]}
    assert set(items) == {v.value for v in ids.values()}
    scoped, global_, assertion = (
        items[ids["scoped"].value],
        items[ids["global"].value],
        items[ids["assertion"].value],
    )
    assert (scoped["type"], scoped["title"], scoped["requires"]) == (
        "knowledge",
        "Retry policy",
        "agent_or_user",
    )
    assert scoped["decidable_by_caller"] is True and scoped["evidence_count"] is None
    assert scoped["consolidation_id"] is None and scoped["applicability"]["project_key"] == "acme"
    assert (global_["requires"], global_["decidable_by_caller"]) == ("user", False)
    assert assertion["type"] == "assertion" and assertion["evidence_count"] == 1
    assert assertion["predicate"] == "supports" and assertion["object_id"] == ids["scoped"].value
    assert len(_result(first_page)["items"]) == 1 and cursor
    assert len(_result(second_page)["items"]) == 2


def test_a_user_accepts_in_a_terminal_and_the_decision_names_the_user(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _seed(store, lambda e: e.capture("g"))
    _user(monkeypatch, tty=True)

    code, envelope = run_json(capsys, _accept(record, "u1"))

    result = _result(envelope)
    assert code == 0
    assert (result["status"], result["basis"], result["pinned_revision"]) == ("accepted", "user", 1)
    assert result["applied"] is True and result["decision_seq"] == 1 and result["effects"] == []
    (decision,) = _log(capsys, record)
    assert decision["actor"]["kind"] == "user" and decision["actor"]["session"] is None


def test_a_rejected_proposal_with_a_new_project_writes_nothing(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-002: a kind-matrix violation must not create the project it names."""
    k, _ = _seed(store, _pair)
    _agent(monkeypatch)
    digest = graph_digest(store)

    code, envelope = run_json(capsys, _propose("supersedes", k, k, "bad-kind", project="brand-new"))
    kind_code, kind = run_json(
        capsys,
        _propose("recommends", RecordId(value=MISSING_ID), k, "bad-ref", project="brand-new"),
    )

    assert code == kind_code == 1
    assert _error(envelope)["code"] == _error(kind)["code"] == "KNOWLEDGE_020_INVALID_ASSERTION"
    assert graph_digest(store) == digest
