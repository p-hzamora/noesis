"""`noesis remember` against the pinned Neo4j container, in-process: AC-012, AC-013 and its failure rows."""

import pytest
from tests.support.knowledge_cli_support import COMMIT_SOURCE, run_json, use_store
from tests.support.knowledge_neo4j_support import query
from tests.support.review_support import graph_digest

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

BODY = "Always retry idempotent payment calls with exponential backoff and jitter."


@pytest.fixture
def store(
    neo4j_settings: Neo4jConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Neo4jConnectionSettings:
    """An initialised database the CLI is configured for."""
    use_store(monkeypatch, neo4j_settings)
    code, _ = run_json(capsys, ["store", "init"])
    assert code == 0
    return neo4j_settings


def _remember(
    capsys: pytest.CaptureFixture[str], *extra: str, body: str = BODY, project: str = "demo"
) -> tuple[int, dict[str, object]]:
    return run_json(
        capsys,
        [
            "remember",
            "--as",
            "knowledge",
            "--subtype",
            "decision",
            "--title",
            "Retry policy",
            "--body",
            body,
            "--project",
            project,
            "--source",
            COMMIT_SOURCE,
            *extra,
        ],
    )


def _result(envelope: dict[str, object]) -> dict[str, object]:
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert isinstance(result, dict)
    return result


def _count(settings: Neo4jConnectionSettings, label: str) -> int:
    rows = query(settings, f"MATCH (n:{label}) RETURN count(n) AS c")  # type: ignore[arg-type]
    return int(rows[0]["c"])


def test_remember_reconciles_duplicate(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-012: a near-identical memory is written, reported as a duplicate, and nothing is merged."""
    _, first = _remember(capsys, "--idempotency-key", "k-first")
    first_id = str(_result(first)["record_id"])

    code, second = _remember(capsys, "--idempotency-key", "k-second")

    result = _result(second)
    duplicates = result["reconciliation"]["duplicates"]  # type: ignore[index]
    assert code == 0 and result["written"] is True
    assert [item["id"] for item in duplicates] == [first_id]
    assert result["status"] == "proposed" and result["record_id"] != first_id
    assert any("consolidation propose" in str(step) for step in result["next_steps"])  # type: ignore[attr-defined]
    assert _count(store, "Knowledge") == 2
    assert query(store, "MATCH (r:Record {id: $id}) RETURN r.status AS s", id=first_id) == [
        {"s": "proposed"}
    ]


def test_remember_check_is_read_only(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-013: `--check` reports the duplicate and leaves the whole graph as it was."""
    _remember(capsys, "--idempotency-key", "k-first")
    before = graph_digest(store)

    code, checked = _remember(capsys, "--check")

    result = _result(checked)
    assert code == 0 and result["written"] is False
    assert len(result["reconciliation"]["duplicates"]) == 1  # type: ignore[index]
    assert graph_digest(store) == before


def test_remember_same_key_with_another_request_is_refused(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    _remember(capsys, "--idempotency-key", "k-1")
    before = graph_digest(store)

    code, envelope = _remember(capsys, "--idempotency-key", "k-1", body="A different lesson.")

    assert code == 1 and envelope["ok"] is False
    assert envelope["error"]["code"] == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"  # type: ignore[index]
    assert graph_digest(store) == before


def test_remember_repeated_command_replays_without_writing(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    _, first = _remember(capsys)
    _, again = _remember(capsys)

    assert _result(again)["replayed"] is True
    assert _result(again)["record_id"] == _result(first)["record_id"]
    assert _count(store, "Knowledge") == 1


def test_remember_refines_proposes_an_assertion_that_persists(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """WP-17: the `refines` predicate is stored and read back."""
    _, target = _remember(capsys, "--idempotency-key", "k-target", body="Pay with cards.")
    target_id = str(_result(target)["record_id"])

    code, refined = _remember(
        capsys,
        "--refines",
        target_id,
        "--idempotency-key",
        "k-refines",
        body="Pay with cards, retrying declines twice.",
    )

    result = _result(refined)
    (assertion,) = result["assertions"]  # type: ignore[misc]
    assert code == 0
    assert (assertion["predicate"], assertion["status"]) == ("refines", "proposed")
    rows = query(
        store,
        "MATCH (a:Record {id: $id}) RETURN a.predicate AS predicate",
        id=assertion["id"],
    )
    assert rows == [{"predicate": "refines"}]


def test_remember_partial_failure_keeps_the_record_and_a_rerun_does_not_duplicate_it(
    store: Neo4jConnectionSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old record belongs to another project, so `supersedes` fails after the record is written."""
    _, old = _remember(capsys, "--idempotency-key", "k-old", project="other", body="Old lesson.")
    old_id = str(_result(old)["record_id"])

    code, first = _remember(capsys, "--supersedes", old_id, "--idempotency-key", "k-new")
    rerun_code, rerun = _remember(capsys, "--supersedes", old_id, "--idempotency-key", "k-new")

    for envelope in (first, rerun):
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "KNOWLEDGE_296_REMEMBER_PARTIALLY_APPLIED"  # type: ignore[index]
    assert code == rerun_code == 1
    assert _count(store, "Knowledge") == 2


def test_retrieval_never_promotes(
    store: Neo4jConnectionSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-015: 100 searches of a proposed memory leave its status, authority and graph unchanged."""
    _remember(capsys, "--idempotency-key", "k-read")
    before = graph_digest(store)

    for _ in range(100):
        code, found = run_json(capsys, ["search", "retry payment backoff", "--project", "demo"])
        assert code == 0, found

    assert graph_digest(store) == before
    assert query(store, "MATCH (r:Knowledge) RETURN r.status AS s") == [{"s": "proposed"}]
