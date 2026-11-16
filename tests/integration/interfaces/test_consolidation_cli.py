"""`noesis consolidation` in-process: usage errors with no I/O, then the commands over Neo4j."""

from typing import Any

import pytest
from tests.support.consolidation_support import (
    ConsolidationEnv,
    raw_consolidations,
    run_with_consolidation,
)
from tests.support.knowledge_cli_support import run_json, use_closed_store, use_store
from tests.support.knowledge_support import AGENT
from tests.support.review_support import (
    AGENT_SESSION,
    attach_terminal,
    graph_digest,
    stored_status,
)

from noesis.interfaces.cli import run
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

ID_A = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
ID_B = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
BODY = ["--title", "T", "--body", "B", "--rationale", "R"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["consolidation", "scan"],
        ["consolidation", "scan", "--record", ID_A, "--project", "acme"],
        ["consolidation", "scan", "--record", ID_A, "--global"],
        ["consolidation", "scan", "--record", "not-an-id"],
        ["consolidation", "scan", "--global", "--limit", "0"],
        ["consolidation", "scan", "--global", "--limit", "51"],
        ["consolidation", "scan", "--global", "--anchors", "101"],
        ["consolidation", "scan", "--record", ID_A, "--cursor", "x"],
        ["consolidation", "scan", "--project", "bad key!"],
        ["consolidation", "propose", "--member", ID_A, *BODY, "--dry-run"],
        ["consolidation", "propose", "--member", ID_A, "--member", ID_A, *BODY, "--dry-run"],
        ["consolidation", "propose", *[x for _ in range(11) for x in ("--member", ID_A)], *BODY],
        ["consolidation", "propose", "--member", ID_A, "--member", "nope", *BODY, "--dry-run"],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            "--body",
            "B",
            "--rationale",
            "R",
            "--dry-run",
        ],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            "--title",
            " ",
            "--body",
            "B",
            "--rationale",
            "R",
            "--dry-run",
        ],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            "--title",
            "T",
            "--rationale",
            "R",
            "--dry-run",
        ],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            "--title",
            "T",
            "--body",
            "B",
            "--rationale",
            " ",
            "--dry-run",
        ],
        ["consolidation", "propose", "--member", ID_A, "--member", ID_B, *BODY],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            *BODY,
            "--dry-run",
            "--tag",
            "Bad Tag",
        ],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            *BODY,
            "--dry-run",
            "--source",
            "nokind",
        ],
        [
            "consolidation",
            "propose",
            "--member",
            ID_A,
            "--member",
            ID_B,
            *BODY,
            "--dry-run",
            "--reconsider",
            "x",
        ],
        ["consolidation", "show", "not-an-id"],
        ["consolidation", "list"],
        ["consolidation", "list", "--project", "acme", "--global"],
        ["consolidation", "list", "--global", "--limit", "101"],
        ["consolidation", "accept", ID_A, "--yes"],
        ["consolidation", "accept", "not-an-id"],
        ["consolidation", "reject", ID_A, "--reason", "x"],
        ["consolidation", "reject", ID_A, "--reason-kind", "distinct", "--reason", " "],
        ["consolidation", "reject", ID_A, "--reason-kind", "distinct", "--reason", "x", "--yes"],
        ["consolidation", "reject", ID_A, "--reason-kind", "nonsense", "--reason", "x"],
    ],
)
def test_usage_errors_exit_2_before_any_io(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)  # a store call would surface as exit 1 after a connect timeout
    assert run(argv) == 2
    capsys.readouterr()


@pytest.mark.unit
def test_help_needs_no_store(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["consolidation", "--help"], ["consolidation", "accept", "--help"]):
        assert run(argv) == 0
    out = capsys.readouterr().out
    assert "propose" in out and "--idempotency-key" in out


@pytest.fixture
def store(
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Neo4jConnectionSettings:
    """An initialised database (every registered step) in space `default`, the CLI configured."""
    use_store(monkeypatch, neo4j_settings)
    monkeypatch.setenv("NOESIS_KNOWLEDGE_SPACE", "default")
    code, _ = run_json(capsys, ["store", "init"])
    assert code == 0
    return neo4j_settings


def _agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", AGENT_SESSION)


def _user(monkeypatch: pytest.MonkeyPatch, *, tty: bool = True) -> None:
    monkeypatch.delenv("NOESIS_SESSION_ID", raising=False)
    attach_terminal(monkeypatch, tty=tty)


def _ok(envelope: dict[str, object]) -> dict[str, Any]:
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


def _err(envelope: dict[str, object]) -> dict[str, Any]:
    assert envelope["ok"] is False, envelope
    error = envelope["error"]
    assert isinstance(error, dict)
    return error


def _pair(settings: Neo4jConnectionSettings, *, project: str | None = "acme") -> list[str]:
    async def seed(env: ConsolidationEnv) -> list[str]:
        return [
            (await env.seed("cli-a", project=project, title="Retry the call")).value,
            (await env.seed("cli-b", project=project, title="Retry the call twice")).value,
        ]

    return run_with_consolidation(settings, seed)


def _propose(members: list[str], key: str | None = "cp1", *extra: str) -> list[str]:
    argv = ["consolidation", "propose", *BODY]
    for member in members:
        argv += ["--member", member]
    return [*argv, *(["--idempotency-key", key] if key else []), *extra]


@pytest.mark.integration
@pytest.mark.neo4j
def test_propose_accept_and_show_as_an_agent_in_a_project(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    members = _pair(store)
    _agent(monkeypatch)
    before = graph_digest(store)

    code, envelope = run_json(capsys, _propose(members, None, "--dry-run"))
    dry = _ok(envelope)
    assert code == 0 and dry["dry_run"] is True and dry["consolidation_id"] is None
    assert graph_digest(store) == before

    code, envelope = run_json(capsys, _propose(members))
    proposed = _ok(envelope)
    cid = proposed["consolidation_id"]
    assert code == 0 and proposed["state"] == "materialised" and not proposed["replayed"]
    assert proposed["link_policy"] == "preserve_originals" and len(proposed["assertions"]) == 2

    code, envelope = run_json(capsys, ["consolidation", "show", cid])
    shown = _ok(envelope)
    assert shown["progress"] == "pending" and shown["decidable_by_caller"] is True

    code, envelope = run_json(capsys, ["consolidation", "list", "--project", "acme"])
    assert [item["id"] for item in _ok(envelope)["items"]] == [cid]

    digest = graph_digest(store)
    code, envelope = run_json(capsys, ["consolidation", "accept", cid])
    assert code == 0 and graph_digest(store) == digest  # a preview writes nothing
    assert {s["outcome"] for s in _ok(envelope)["steps"]} == {"planned"}

    code, envelope = run_json(
        capsys, ["consolidation", "accept", cid, "--yes", "--idempotency-key", "cacc"]
    )
    done = _ok(envelope)
    assert code == 0 and done["progress"] == "applied" and done["state"] == "acceptance_started"
    assert stored_status(store, members[0]) == "superseded"


@pytest.mark.integration
@pytest.mark.neo4j
def test_a_global_consolidation_is_refused_for_an_agent_and_needs_a_terminal_for_the_user(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    members = _pair(store, project=None)
    _agent(monkeypatch)
    _, envelope = run_json(capsys, _propose(members))
    cid = _ok(envelope)["consolidation_id"]
    assert _ok(envelope)["requires"] == "user"
    digest = graph_digest(store)

    code, envelope = run_json(
        capsys, ["consolidation", "accept", cid, "--yes", "--idempotency-key", "k"]
    )
    assert code == 1 and _err(envelope)["code"] == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert graph_digest(store) == digest

    _user(monkeypatch, tty=False)
    code, envelope = run_json(
        capsys, ["consolidation", "accept", cid, "--yes", "--idempotency-key", "k"]
    )
    assert code == 2 or _err(envelope)["code"].startswith("INTERFACE")
    assert graph_digest(store) == digest

    _user(monkeypatch)
    code, envelope = run_json(
        capsys, ["consolidation", "accept", cid, "--yes", "--idempotency-key", "k"]
    )
    assert code == 0 and _ok(envelope)["progress"] == "applied"


@pytest.mark.integration
@pytest.mark.neo4j
def test_reject_dismisses_and_a_failed_step_exits_1_with_every_step(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    members = _pair(store)
    _agent(monkeypatch)
    _, envelope = run_json(capsys, _propose(members))
    cid = _ok(envelope)["consolidation_id"]
    successor = _ok(envelope)["successor_id"]

    code, envelope = run_json(
        capsys,
        [
            "consolidation",
            "reject",
            cid,
            "--reason-kind",
            "distinct",
            "--reason",
            "different",
            "--yes",
            "--idempotency-key",
            "crej",
        ],
    )
    done = _ok(envelope)
    assert (
        code == 0
        and done["state"] == "dismissed"
        and stored_status(store, successor) == "retracted"
    )
    assert raw_consolidations(store)[0]["dismissal_reason_kind"] == "distinct"

    code, envelope = run_json(
        capsys, ["consolidation", "accept", cid, "--yes", "--idempotency-key", "x"]
    )
    assert code == 1 and _err(envelope)["code"] == "KNOWLEDGE_093_CONSOLIDATION_CLOSED"
    code, envelope = run_json(capsys, _propose(members, "again"))
    assert code == 1 and _err(envelope)["code"] == "KNOWLEDGE_292_DISMISSED_CONSOLIDATION_PAIR"

    code, envelope = run_json(capsys, _propose(members, "again2", "--reconsider", cid))
    second = _ok(envelope)
    assert code == 0 and second["state"] == "materialised"
    # retract the new successor behind the command's back: accept now fails its first step
    from tests.support.review_commands import retract_knowledge_command
    from tests.support.review_support import run_with_handlers

    from noesis.bounded_context.knowledge.domain.value_objects import RecordId

    run_with_handlers(
        store,
        lambda env: env.retract_knowledge().handle(
            retract_knowledge_command(RecordId(value=second["successor_id"]), "behind")
        ),
    )
    code, envelope = run_json(
        capsys,
        ["consolidation", "accept", second["consolidation_id"], "--yes", "--idempotency-key", "kx"],
    )
    error = _err(envelope)
    assert code == 1 and error["code"] == "KNOWLEDGE_295_CONSOLIDATION_PARTIALLY_APPLIED"
    assert {s["outcome"] for s in error["metadata"]["steps"]} == {"failed", "not_run"}
    assert any("--idempotency-key kx" in step for step in error["next_steps"])


@pytest.mark.integration
@pytest.mark.neo4j
def test_scan_over_the_real_search_pipeline_finds_lexical_overlap(
    store: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    members = _pair(store)
    _agent(monkeypatch)
    from tests.support.knowledge_neo4j_support import query

    query(store, "CALL db.awaitIndexes(30)")

    code, envelope = run_json(capsys, ["consolidation", "scan", "--record", members[0]])

    scanned = _ok(envelope)
    assert code == 0 and scanned["semantic_state"] == "absent"
    assert [c["record_id"] for g in scanned["groups"] for c in g["candidates"]] == [members[1]]
    assert "similarity" not in str(scanned)
    assert AGENT.kind.value == "agent"
