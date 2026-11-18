"""`noesis import run` and `noesis import file` as real child processes (C3 acceptance and edge cases).

Every child gets an explicit minimal environment: `NOESIS_VAULT_DIR` is a copy of the fixture
vault under `tmp_path`, `NOESIS_IMPORT_VAULT_KEY=fixture`, `NOESIS_KNOWLEDGE_SPACE=personal`,
`NOESIS_NEO4J_*` of the test container (or a closed port) and no harness marker, so the actor is
`user`. The user's vault and settings are never read (NFR-001, C2 NFR-004). A shared fixture
compares `file_snapshot` of every vault or folder a test touches before and after the test,
apart from the test's own edits (`Folder.write`, `append`, `move`).
"""

import hashlib
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from tests.support.import_support import (
    C1SHA,
    CLEAN_TOTALS,
    FIXTURE_VAULT,
    FULL_BLOCKED_REASONS,
    FULL_TOTALS,
    K1,
    K2,
    K3,
    K5,
    K6,
    K7,
    K8,
    K9,
    N1,
    N2,
    N3,
    N5,
    N6,
    N7,
    N8,
    N9,
    N10,
    N11,
    N12,
    N13,
    N14,
    N15,
    N16,
    N17,
    copy_fixture_vault,
    expected_body,
    file_snapshot,
    graph_counts,
    graph_digest,
    graph_session,
    knowledge_by_locator,
    ledger_keys,
    seed_status,
)
from tests.support.knowledge_cli_support import closed_port
from tests.support.noesis_process_support import (
    ProcessResult,
    finish,
    run_noesis,
    start_noesis,
    store_environment,
)

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SPACE = "personal"
VAULT_KEY = "fixture"
ZERO_TOTALS = dict.fromkeys(CLEAN_TOTALS, 0)
NOT_FOUND = "KNOWLEDGE_201_RECORD_NOT_FOUND"
UNAVAILABLE = "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


@dataclass
class Folder:
    """A folder of the test (a vault or a folder of outside files) guarded by a snapshot."""

    root: Path
    expected: dict[str, tuple[str, str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.expected = file_snapshot(self.root)

    def write(self, relative: str, data: bytes) -> None:
        """Change a file as the test's own edit; the guard's expectation follows."""
        target: Path = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.expected = file_snapshot(self.root)

    def append(self, relative: str, text: str) -> None:
        """Append `text` to a file as the test's own edit."""
        self.write(relative, (self.root / relative).read_bytes() + text.encode())

    def read(self, relative: str) -> bytes:
        """The bytes of a file."""
        return (self.root / relative).read_bytes()

    def move(self, source: str, destination: str) -> None:
        """Move a file as the test's own edit."""
        target: Path = self.root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self.root / source, target)
        self.expected = file_snapshot(self.root)

    def assert_untouched(self) -> None:
        """Nothing under the folder differs from the last snapshot (bytes, mtimes, listing)."""
        assert file_snapshot(self.root) == self.expected


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[Folder]:
    """The clean fixture vault; guarded: no command may change it."""
    guarded = Folder(copy_fixture_vault(tmp_path))
    yield guarded
    guarded.assert_untouched()


@pytest.fixture
def full_vault(tmp_path: Path) -> Iterator[Folder]:
    """The full fixture vault (with `inbox/`); guarded."""
    guarded = Folder(copy_fixture_vault(tmp_path, clean=False))
    yield guarded
    guarded.assert_untouched()


@pytest.fixture
def outside(tmp_path: Path) -> Iterator[Folder]:
    """A folder outside any vault for `import file`; guarded."""
    root: Path = tmp_path / "outside"
    root.mkdir()
    guarded = Folder(root)
    yield guarded
    guarded.assert_untouched()


def child_env(
    tmp_path: Path,
    settings: Neo4jConnectionSettings,
    vault_dir: Path | None,
    *,
    key: str | None = VAULT_KEY,
    timeout: str | None = None,
) -> dict[str, str]:
    """The child environment: the store of `settings` and the vault of `vault_dir`."""
    extra: dict[str, str] = {}
    if vault_dir is not None:
        extra["NOESIS_VAULT_DIR"] = str(vault_dir)
    if key is not None:
        extra["NOESIS_IMPORT_VAULT_KEY"] = key
    if timeout is not None:
        extra["NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS"] = timeout
    return store_environment(tmp_path / "child-home", SPACE, settings, **extra)


def closed_env(
    tmp_path: Path, vault_dir: Path | None, *, key: str | None = VAULT_KEY
) -> dict[str, str]:
    """A child environment whose Neo4j URI is a closed local port."""
    settings = Neo4jConnectionSettings(
        uri=f"bolt://127.0.0.1:{closed_port()}", user="neo4j", password=SecretStr("never-sent")
    )
    return child_env(tmp_path, settings, vault_dir, key=key, timeout="2")


@pytest.fixture
def env(tmp_path: Path, vault: Folder, neo4j_settings: Neo4jConnectionSettings) -> dict[str, str]:
    """The child environment over the wiped container and the clean fixture vault."""
    return child_env(tmp_path, neo4j_settings, vault.root)


@pytest.fixture
def ready(env: dict[str, str]) -> dict[str, str]:
    """`env` after `store init`."""
    assert run_noesis(["store", "init"], env).code == 0
    return env


def preview(env: dict[str, str], *flags: str) -> ProcessResult:
    """`import run --json --verbose` (a preview)."""
    return run_noesis(["import", "run", "--verbose", *flags], env)


def apply(env: dict[str, str], *flags: str) -> ProcessResult:
    """`import run --yes --json --verbose`."""
    return run_noesis(["import", "run", "--yes", "--verbose", *flags], env)


def rows(result: ProcessResult) -> dict[str, dict[str, Any]]:
    """The verbose rows of a run by path."""
    notes: Any = result.result["notes"]
    return {item["path"]: item for item in notes}


def record(env: dict[str, str], record_id: str, *flags: str) -> dict[str, Any]:
    """`record get` of a record that must exist; the result."""
    fetched = run_noesis(["record", "get", record_id, *flags], env)
    assert fetched.code == 0, fetched.stdout
    return fetched.result  # type: ignore[return-value]


def graph(settings: Neo4jConnectionSettings) -> tuple[dict[str, Any], str]:
    """Counts and digest of the whole graph."""
    with graph_session(settings) as session:
        return graph_counts(session), graph_digest(session)


def digest(settings: Neo4jConnectionSettings) -> str:
    """The graph digest."""
    return graph(settings)[1]


def knowledge_count(settings: Neo4jConnectionSettings) -> int:
    """Number of `:Knowledge` nodes."""
    with graph_session(settings) as session:
        row = session.run("MATCH (k:Knowledge) RETURN count(k) AS c").single()
    assert row is not None
    return int(row["c"])


def sha256_of(data: bytes) -> str:
    """`sha256:<hex>`."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def error_of(result: ProcessResult) -> dict[str, Any]:
    """A failed command's error object, with exit code 1 asserted."""
    assert result.code == 1, (result.code, result.stdout, result.stderr)
    return result.error  # type: ignore[return-value]


# --------------------------------------------------------------------------- acceptance criteria


def test_ac003_preview_writes_nothing(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    d0: str = digest(neo4j_settings)

    first = preview(ready)

    result = first.result
    assert first.code == 0 and result["applied"] is False
    assert result["totals"] == CLEAN_TOTALS
    by_path = rows(first)
    for path, record_id in ((N1, K1), (N2, K2), (N3, K3), (N5, K5)):
        assert (
            by_path[path]["outcome"],
            by_path[path]["record_id"],
            by_path[path]["revision"],
        ) == (
            "created",
            record_id,
            1,
        )
    for path in (N7, N8):
        assert (by_path[path]["outcome"], by_path[path]["record_id"]) == ("created", None)
    assert "noesis import run --yes" in result["next_steps"]  # type: ignore[operator]
    assert digest(neo4j_settings) == d0

    assert apply(ready).code == 0
    vault.append(N2, "Extra step.\n")
    d1: str = digest(neo4j_settings)
    reported = preview(ready)
    updating = preview(ready, "--update")

    assert (rows(reported)[N2]["outcome"], rows(reported)[N2]["revision"]) == (
        "changed_in_vault",
        1,
    )
    assert (rows(updating)[N2]["outcome"], rows(updating)[N2]["revision"]) == ("revised", 2)
    assert "noesis import run --yes --update" in updating.result["next_steps"]  # type: ignore[operator]
    assert digest(neo4j_settings) == d1


def test_ac005_rerun_changes_nothing(
    ready: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    first = apply(ready)
    counts, d1 = graph(neo4j_settings)

    second = apply(ready)

    assert second.code == 0
    assert second.result["totals"] == {
        **ZERO_TOTALS,
        "notes": 10,
        "unchanged": 7,
        "skipped_empty": 3,
    }
    assert {p: r["record_id"] for p, r in rows(second).items()} == {
        p: r["record_id"] for p, r in rows(first).items()
    }
    assert graph(neo4j_settings) == (counts, d1)


def test_ac006_edit_and_revert_make_revisions(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    apply(ready)
    original: bytes = vault.read(N2)
    vault.append(N2, "Extra step.\n")

    second = apply(ready, "--update")
    vault.write(N2, original)
    third = apply(ready, "--update")

    assert (
        rows(second)[N2]["outcome"],
        rows(second)[N2]["revision"],
        rows(second)[N2]["status"],
    ) == (
        "revised",
        2,
        "proposed",
    )
    assert (rows(third)[N2]["outcome"], rows(third)[N2]["revision"]) == ("revised", 3)
    assert all(
        row["outcome"] in ("unchanged", "skipped_empty")
        for path, row in rows(second).items()
        if path != N2
    )
    one = record(ready, K2, "--revision", "1")["revision"]
    three = record(ready, K2, "--revision", "3")["revision"]
    assert (one["title"], one["body"]) == (three["title"], three["body"])
    file_digests = [s["digest"] for s in three["sources"] if s["kind"] == "file_version"]
    assert file_digests == [s["digest"] for s in one["sources"] if s["kind"] == "file_version"]
    assert len(file_digests) == 1
    with graph_session(neo4j_settings) as session:
        revisions = session.run(
            "MATCH (:Revision {record_id: $id}) RETURN count(*) AS c", id=K2
        ).single()
        keys = ledger_keys(session)
    assert revisions is not None and revisions["c"] == 3
    assert len([k for k in keys if k.startswith(f"import/v1/revise/{K2}/1/")]) == 1
    assert len([k for k in keys if k.startswith(f"import/v1/revise/{K2}/2/")]) == 1


def test_ac008_moved_note_with_ulid_writes_nothing(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    apply(ready)
    vault.move(N1, "archive/ports.md")
    before: str = digest(neo4j_settings)

    moved = apply(ready)

    moved_row = rows(moved)["archive/ports.md"]
    assert (moved_row["outcome"], moved_row["record_id"], moved_row["revision"]) == (
        "unchanged",
        K1,
        1,
    )
    assert moved.result["totals"]["unchanged"] == 7 and moved.result["totals"]["created"] == 0  # type: ignore[index]
    assert digest(neo4j_settings) == before


def test_ac009_blocked_notes_skipped(
    tmp_path: Path, full_vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    env = child_env(tmp_path, neo4j_settings, full_vault.root)
    assert run_noesis(["store", "init"], env).code == 0

    applied = apply(env)

    result = applied.result
    assert applied.code == 0 and result["complete"] is False
    assert result["totals"] == FULL_TOTALS and result["blocked_reasons"] == FULL_BLOCKED_REASONS
    by_path = rows(applied)
    expected: dict[str, str] = {
        N11: "invalid_id",
        N12: "duplicate_id",
        N13: "duplicate_id",
        N14: "invalid_header",
        N15: "not_text",
        N16: "invalid_scope",
        N17: "invalid_metadata",
    }
    for path, reason in expected.items():
        assert (by_path[path]["outcome"], by_path[path]["reason"]) == ("blocked", reason)
    assert by_path[N17]["detail"] == "KNOWLEDGE_002_INVALID_SLUG"
    for missing in (K7, K8, K9):
        assert error_of(run_noesis(["record", "get", missing], env))["code"] == NOT_FOUND
    assert "noesis import run --verbose" in result["next_steps"]  # type: ignore[operator]


def test_ac009_strict_refuses(
    tmp_path: Path,
    full_vault: Folder,
    vault_clean_with_bad_kind: Folder,
    neo4j_settings: Neo4jConnectionSettings,
) -> None:
    env = child_env(tmp_path, neo4j_settings, full_vault.root)
    assert run_noesis(["store", "init"], env).code == 0
    d0: str = digest(neo4j_settings)
    interop_reasons = {k: v for k, v in FULL_BLOCKED_REASONS.items() if k != "invalid_metadata"}

    for flags in (["--yes", "--strict"], ["--strict"]):
        refused = run_noesis(["import", "run", *flags], env)
        error = error_of(refused)
        assert error["code"] == "IMPORT_201_BLOCKING_FINDINGS"
        assert error["metadata"]["blocked_reasons"] == interop_reasons
    assert digest(neo4j_settings) == d0

    only_bad_kind = child_env(tmp_path, neo4j_settings, vault_clean_with_bad_kind.root)
    refused = run_noesis(["import", "run", "--strict", "--yes"], only_bad_kind)
    assert error_of(refused)["code"] == "IMPORT_201_BLOCKING_FINDINGS"
    assert error_of(refused)["metadata"]["blocked_reasons"] == {"invalid_metadata": 1}
    assert digest(neo4j_settings) == d0


@pytest.fixture
def vault_clean_with_bad_kind(tmp_path: Path) -> Iterator[Folder]:
    """The clean fixture plus only N17 (found by the assess pass, not by interop)."""
    root: Path = copy_fixture_vault(tmp_path, name="vault-bad-kind")
    (root / "inbox").mkdir()
    shutil.copy(FIXTURE_VAULT / N17, root / N17)
    guarded = Folder(root)
    yield guarded
    guarded.assert_untouched()


def test_ac011_store_down_fails_closed(tmp_path: Path, vault: Folder, outside: Folder) -> None:
    outside.write("design.md", b"# Design\n\nA file.\n")
    env = closed_env(tmp_path, vault.root)

    for args in (
        ["import", "run"],
        ["import", "run", "--yes"],
        ["import", "file", str(outside.root / "design.md")],
    ):
        failed = run_noesis(args, env)
        error = error_of(failed)
        assert error["code"] == UNAVAILABLE
        assert error["next_steps"]
    vault.assert_untouched()
    outside.assert_untouched()


def test_ac012_vault_untouched(ready: dict[str, str], vault: Folder) -> None:
    before = file_snapshot(vault.root)
    assert "repos/alpha/linked.md" in before and before["repos/alpha/linked.md"][0] == "link"
    assert ".obsidian/hidden.md" in before

    for args in ([], ["--yes"], ["--yes"], ["--yes", "--update"]):
        assert run_noesis(["import", "run", *args], ready).code == 0

    assert file_snapshot(vault.root) == before


def test_ac020_migrated_record_shape(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    applied = apply(ready)
    by_path = rows(applied)

    k1 = record(ready, K1)

    assert (k1["type"], k1["ownership"], k1["status"], k1["head_revision"]) == (
        "knowledge",
        "graph",
        "proposed",
        1,
    )
    assert (k1["revision"]["title"], k1["revision"]["body"]) == (
        "Ports and adapters",
        expected_body("B1"),
    )
    assert k1["subtype"] == "concept"
    assert k1["applicability"]["tags"] == ["architecture", "origin:migrated", "python"]
    project = record(ready, k1["project_id"])
    assert (project["type"], project["key"]) == ("project", "alpha")
    assert sorted((s["kind"], s["locator"], s["digest"]) for s in k1["sources"]) == sorted(
        [
            ("file_version", f"vault://{VAULT_KEY}/{N1}", sha256_of(vault.read(N1))),
            ("commit", C1SHA, None),
        ]
    )
    assert k1["revision"]["actor"]["kind"] == "user"
    assert "2026-11-01" not in str(k1)

    k2 = record(ready, K2)
    assert (k2["revision"]["title"], k2["revision"]["body"]) == (
        "Capture a note",
        expected_body("B2"),
    )
    k3 = record(ready, K3)
    assert k3["project_id"] is None
    assert k3["applicability"]["tags"] == ["origin:migrated", "topic:python"]
    assert k3["revision"]["title"] == "diseño hexagonal"

    id7, id8 = by_path[N7]["record_id"], by_path[N8]["record_id"]
    assert sorted(by_path[N7]["warnings"]) == [
        "dropped_tag:two words",
        "ignored_field:id",
        "ignored_field:status",
        "legacy_header",
    ]
    n7, n8 = record(ready, id7), record(ready, id8)
    assert [s["kind"] for s in n7["sources"]] == ["file_version"]
    assert [s["kind"] for s in n8["sources"]] == ["file_version"]
    assert n7["subtype"] == "learning"
    assert n7["applicability"]["tags"] == [
        "area:backend",
        "draft",
        "origin:migrated",
        "topic:python",
    ]
    assert n8["subtype"] == "note" and n8["revision"]["title"] == "README"
    assert n8["applicability"]["tags"] == ["origin:migrated"]
    assert len(id7) == 26 and len(id8) == 26


def test_ac021_empty_notes_skipped(
    ready: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    applied = apply(ready)

    by_path = rows(applied)
    assert [by_path[p]["outcome"] for p in (N6, N9, N10)] == ["skipped_empty"] * 3
    assert (by_path[N6]["record_id"], by_path[N10]["record_id"], by_path[N9]["record_id"]) == (
        None,
        None,
        K6,
    )
    assert error_of(run_noesis(["record", "get", K6], ready))["code"] == NOT_FOUND
    with graph_session(neo4j_settings) as session:
        for path in (N6, N9, N10):
            assert knowledge_by_locator(session, f"vault://{VAULT_KEY}/{path}") == []
    assert knowledge_count(neo4j_settings) == 7


def test_ac022_changed_note_is_reported_only(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    apply(ready)
    vault.append(N5, "Also fast.\n")
    d: str = digest(neo4j_settings)

    reported = apply(ready)

    assert reported.code == 0
    row = rows(reported)[N5]
    assert (row["outcome"], row["record_id"], row["revision"]) == ("changed_in_vault", K5, 1)
    assert reported.result["totals"]["changed_in_vault"] == 1  # type: ignore[index]
    assert reported.result["complete"] is True
    assert "noesis import run --yes --update" in reported.result["next_steps"]  # type: ignore[operator]
    assert digest(neo4j_settings) == d


def test_ac024_note_without_ulid_found_by_locator(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    first = apply(ready)
    id7, id8 = rows(first)[N7]["record_id"], rows(first)[N8]["record_id"]

    second = apply(ready)

    assert (rows(second)[N7]["outcome"], rows(second)[N7]["record_id"]) == ("unchanged", id7)
    assert (rows(second)[N8]["outcome"], rows(second)[N8]["record_id"]) == ("unchanged", id8)
    assert knowledge_count(neo4j_settings) == 7
    with graph_session(neo4j_settings) as session:
        assert knowledge_by_locator(session, f"vault://{VAULT_KEY}/{N8}") == [id8]
    vault.append(N8, "More.\n")
    edited = apply(ready, "--update")
    assert (
        rows(edited)[N8]["outcome"],
        rows(edited)[N8]["record_id"],
        rows(edited)[N8]["revision"],
    ) == (
        "revised",
        id8,
        2,
    )
    assert knowledge_count(neo4j_settings) == 7


DESIGN = (
    b"---\ntitle: Ignored by option\n---\n# Design\n\nUse [[ports|the ports note]].\n\n"
    b"## Related\n\n- [[x]]\n"
)


def test_ac025_import_file_create_rerun_revise(
    tmp_path: Path, outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    env = child_env(tmp_path, neo4j_settings, None)
    assert run_noesis(["store", "init"], env).code == 0
    outside.write("design.md", DESIGN)
    target: Path = outside.root / "design.md"
    command = [
        "import",
        "file",
        str(target),
        "--title",
        "Design notes",
        "--project",
        "alpha",
        "--tag",
        "area:core",
    ]

    created = run_noesis(command, env)

    assert created.code == 0
    result = created.result
    assert (result["outcome"], result["path"], result["project_key"]) == (
        "created",
        str(target.resolve()),
        "alpha",
    )
    assert "legacy_header" not in result["warnings"]  # type: ignore[operator]
    record_id = str(result["record_id"])
    stored = record(env, record_id)
    assert (stored["ownership"], stored["status"], stored["head_revision"]) == (
        "graph",
        "proposed",
        1,
    )
    assert (stored["revision"]["title"], stored["revision"]["body"]) == (
        "Design notes",
        "# Design\n\nUse the ports note.",
    )
    assert stored["subtype"] == "note"
    assert record(env, stored["project_id"])["key"] == "alpha"
    assert stored["applicability"]["tags"] == ["area:core", "origin:imported"]
    assert [(s["kind"], s["locator"], s["digest"]) for s in stored["sources"]] == [
        ("file_version", str(target.resolve()), sha256_of(DESIGN))
    ]

    before = graph(neo4j_settings)
    again = run_noesis(command, env)
    assert (again.result["outcome"], again.result["record_id"]) == ("unchanged", record_id)
    assert graph(neo4j_settings) == before

    outside.append("design.md", "More.\n")
    dry = run_noesis([*command, "--dry-run"], env)
    assert (dry.result["applied"], dry.result["outcome"], dry.result["revision"]) == (
        False,
        "revised",
        2,
    )
    assert graph(neo4j_settings) == before
    revised = run_noesis(command, env)
    assert (revised.result["outcome"], revised.result["record_id"], revised.result["revision"]) == (
        "revised",
        record_id,
        2,
    )


def test_ac027_import_file_failures(
    tmp_path: Path, outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    env = child_env(tmp_path, neo4j_settings, None)
    assert run_noesis(["store", "init"], env).code == 0
    (outside.root / "dir.md").mkdir()
    outside.write("binary.md", b"\xff\xfe\x00\x01")
    outside.write("header-only.md", b"---\ntitle: x\n---\n")
    outside.write(
        "hub.md", b"# Python\n\n## Concepts\n\n- [[diseno-hexagonal]]\n- [[legacy-note|Legacy]]\n"
    )
    d: str = digest(neo4j_settings)

    for name in ("missing.md", "dir.md"):
        error = error_of(run_noesis(["import", "file", str(outside.root / name)], env))
        assert error["code"] == "IMPORT_102_FILE_READ_FAILED"
        assert "path" in error["metadata"]
    binary = error_of(run_noesis(["import", "file", str(outside.root / "binary.md")], env))
    assert (binary["code"], binary["metadata"]["reason"]) == (
        "IMPORT_203_FILE_NOT_IMPORTABLE",
        "not_text",
    )
    for name in ("header-only.md", "hub.md"):
        error = error_of(run_noesis(["import", "file", str(outside.root / name)], env))
        assert (error["code"], error["metadata"]["reason"]) == (
            "IMPORT_203_FILE_NOT_IMPORTABLE",
            "empty_body",
        )

    assert digest(neo4j_settings) == d
    closed = closed_env(tmp_path, None)
    missing = error_of(run_noesis(["import", "file", str(outside.root / "missing.md")], closed))
    assert missing["code"] == "IMPORT_102_FILE_READ_FAILED"


def test_ac028_graph_revision_not_overwritten(
    ready: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    apply(ready)
    revised = run_noesis(
        [
            "record",
            "revise",
            K3,
            "--expected-revision",
            "1",
            "--body",
            "Curated text.",
            "--idempotency-key",
            "t-ac028",
        ],
        ready,
    )
    assert revised.code == 0

    after = apply(ready, "--update")

    row = rows(after)[N3]
    assert (row["outcome"], row["record_id"], row["revision"]) == ("unchanged", K3, 2)
    assert record(ready, K3)["revision"]["body"] == "Curated text."
    with graph_session(neo4j_settings) as session:
        revisions = session.run(
            "MATCH (:Revision {record_id: $id}) RETURN count(*) AS c", id=K3
        ).single()
    assert revisions is not None and revisions["c"] == 2


# --------------------------------------------------------------------------------- edge cases


def test_two_concurrent_applies_leave_one_record_per_note(
    ready: dict[str, str], neo4j_settings: Neo4jConnectionSettings
) -> None:
    started: float = time.monotonic()
    processes = [start_noesis(["import", "run", "--yes", "--verbose"], ready) for _ in range(2)]
    results = [finish(process, started) for process in processes]

    for result in results:
        assert result.code == 0, result.stderr
        assert result.result["totals"]["blocked"] == 0  # type: ignore[index]
        assert all(
            row["outcome"] in ("created", "unchanged", "skipped_empty")
            for row in rows(result).values()
        )
    counts, _ = graph(neo4j_settings)
    assert counts["labels"]["Knowledge"] == 7 and counts["revisions"] == 7
    third = apply(ready)
    assert third.result["totals"] == {
        **ZERO_TOTALS,
        "notes": 10,
        "unchanged": 7,
        "skipped_empty": 3,
    }  # type: ignore[index]


def test_knowledge_204_when_the_store_was_never_initialised(
    env: dict[str, str], outside: Folder
) -> None:
    outside.write("design.md", b"# Design\n\nA file.\n")

    for args in (["import", "run"], ["import", "file", str(outside.root / "design.md")]):
        error = error_of(run_noesis(args, env))
        assert error["code"] == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
        assert any("noesis store init" in step for step in error["next_steps"])


def test_core_002_without_a_vault_dir_fails_before_the_store_and_import_file_still_works(
    tmp_path: Path, outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    closed = error_of(run_noesis(["import", "run"], closed_env(tmp_path, None)))
    assert closed["code"] == "CORE_002_VAULT_NOT_CONFIGURED"

    env = child_env(tmp_path, neo4j_settings, None)
    assert run_noesis(["store", "init"], env).code == 0
    outside.write("design.md", b"# Design\n\nA file.\n")
    registered = run_noesis(["import", "file", str(outside.root / "design.md")], env)

    assert registered.code == 0 and registered.result["outcome"] == "created"


def test_import_101_for_a_missing_vault_folder_before_any_store_access(tmp_path: Path) -> None:
    missing: Path = tmp_path / "nowhere"

    error = error_of(run_noesis(["import", "run"], closed_env(tmp_path, missing)))

    assert error["code"] == "IMPORT_101_VAULT_READ_FAILED"
    assert str(missing) in str(error["metadata"]["path"])


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_import_101_for_an_unreadable_note_names_it(tmp_path: Path, vault: Folder) -> None:
    locked: Path = vault.root / N1
    locked.chmod(0)
    try:
        error = error_of(run_noesis(["import", "run"], closed_env(tmp_path, vault.root)))
    finally:
        locked.chmod(0o644)

    assert error["code"] == "IMPORT_101_VAULT_READ_FAILED"
    assert N1 in str(error["metadata"]["path"])


def test_an_invalid_vault_key_fails_import_with_core_001_and_never_other_commands(
    tmp_path: Path, vault: Folder
) -> None:
    env = closed_env(tmp_path, vault.root, key="a b")

    refused = error_of(run_noesis(["import", "run"], env))
    other = error_of(run_noesis(["record", "get", K1], env))

    assert refused["code"] == "CORE_001_INVALID_CONFIGURATION"
    assert "NOESIS_IMPORT_VAULT_KEY" in f"{refused['message']} {refused['metadata']}"
    assert other["code"] == UNAVAILABLE


def test_a_vault_folder_that_is_not_a_valid_key_needs_an_explicit_key(tmp_path: Path) -> None:
    spaced: Path = copy_fixture_vault(tmp_path, name="my vault")
    guarded = Folder(spaced)

    error = error_of(run_noesis(["import", "run"], closed_env(tmp_path, spaced, key=None)))

    assert error["code"] == "CORE_001_INVALID_CONFIGURATION"
    assert "NOESIS_IMPORT_VAULT_KEY" in f"{error['message']} {error['metadata']}"
    guarded.assert_untouched()


def test_the_vault_key_defaults_to_the_vault_folder_name(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings
) -> None:
    named: Folder = Folder(copy_fixture_vault(tmp_path, name="my-vault"))
    env = child_env(tmp_path, neo4j_settings, named.root, key=None)
    assert run_noesis(["store", "init"], env).code == 0

    applied = apply(env)

    assert applied.result["vault_key"] == "my-vault"
    sources = record(env, readme_id(applied))["sources"]
    assert [s["locator"] for s in sources] == ["vault://my-vault/README.md"]
    named.assert_untouched()


def readme_id(applied: ProcessResult) -> str:
    """The id minted for README.md."""
    return str(rows(applied)[N8]["record_id"])


def test_an_empty_vault_is_complete_with_zero_counts(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings
) -> None:
    empty: Path = tmp_path / "empty"
    empty.mkdir()
    env = child_env(tmp_path, neo4j_settings, empty)
    assert run_noesis(["store", "init"], env).code == 0

    applied = apply(env)

    assert applied.code == 0
    assert applied.result["totals"] == ZERO_TOTALS and applied.result["complete"] is True


@pytest.mark.parametrize(
    ("args", "complaint"),
    [
        pytest.param(["import", "file"], "Missing argument", id="file-without-path"),
        pytest.param(
            ["import", "file", "{file}", "--update"],
            "No such option: --update",
            id="file-with-update",
        ),
        pytest.param(
            ["import", "file", "{file}", "--strict"],
            "No such option: --strict",
            id="file-with-strict",
        ),
        pytest.param(
            ["import", "run", "--dry-run"], "No such option: --dry-run", id="run-with-dry-run"
        ),
        pytest.param(["import", "run", "--bogus"], "No such option: --bogus", id="unknown-option"),
    ],
)
def test_usage_errors_exit_2_with_no_store_access(
    tmp_path: Path, vault: Folder, outside: Folder, args: list[str], complaint: str
) -> None:
    outside.write("design.md", b"# Design\n\nA file.\n")
    command = [a.replace("{file}", str(outside.root / "design.md")) for a in args]

    failed = run_noesis(command, closed_env(tmp_path, vault.root))

    output = failed.stdout + failed.stderr
    assert failed.code == 2
    assert complaint in output  # a usage error of the `import` command, not "No such command"
    assert "INTEGRATION_103" not in output


def test_a_moved_note_without_a_ulid_creates_a_second_record(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    id8: str = str(rows(apply(ready))[N8]["record_id"])
    vault.move(N8, "misc/README.md")

    moved = apply(ready)

    moved_row = rows(moved)["misc/README.md"]
    assert moved_row["outcome"] == "created" and moved_row["record_id"] not in (None, id8)
    assert record(ready, id8)["id"] == id8
    assert knowledge_count(neo4j_settings) == 8


def test_a_header_only_change_writes_nothing_even_with_update(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    apply(ready)
    changed: bytes = (
        vault.read(N1)
        .replace(b"updated: 2026-11-01", b"updated: 2026-11-02")
        .replace(b"tags: [architecture, Python]", b"tags: [architecture, Python, extra]")
    )
    assert changed != vault.read(N1)
    vault.write(N1, changed)
    before = graph(neo4j_settings)

    updated = apply(ready, "--update")

    assert rows(updated)[N1]["outcome"] == "unchanged"
    assert record(ready, K1)["applicability"]["tags"] == [
        "architecture",
        "origin:migrated",
        "python",
    ]
    assert graph(neo4j_settings) == before


def test_import_file_through_a_symbolic_link_and_through_the_target_share_one_record(
    tmp_path: Path, outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    env = child_env(tmp_path, neo4j_settings, None)
    assert run_noesis(["store", "init"], env).code == 0
    outside.write("real/design.md", b"# Design\n\nA file.\n")
    link: Path = tmp_path / "link.md"
    link.symlink_to(outside.root / "real/design.md")
    target: Path = (outside.root / "real/design.md").resolve()

    through_link = run_noesis(["import", "file", str(link)], env)
    through_target = run_noesis(["import", "file", str(target)], env)

    assert through_link.result["outcome"] == "created"
    assert (through_target.result["outcome"], through_target.result["record_id"]) == (
        "unchanged",
        through_link.result["record_id"],
    )
    sources = record(env, str(through_link.result["record_id"]))["sources"]
    assert [s["locator"] for s in sources] == [str(target)]


def test_import_file_on_a_copy_of_a_migrated_note_creates_a_new_record(
    ready: dict[str, str], vault: Folder, outside: Folder
) -> None:
    apply(ready)
    outside.write("copy.md", vault.read(N1))

    copied = run_noesis(["import", "file", str(outside.root / "copy.md")], ready)

    assert copied.code == 0 and copied.result["outcome"] == "created"
    new_id = str(copied.result["record_id"])
    assert new_id != K1
    assert "origin:imported" in record(ready, new_id)["applicability"]["tags"]
    assert "origin:migrated" not in record(ready, new_id)["applicability"]["tags"]
    original = record(ready, K1)
    assert original["head_revision"] == 1
    assert original["applicability"]["tags"] == ["architecture", "origin:migrated", "python"]


def test_import_file_with_an_invalid_subtype_is_import_203_and_writes_nothing(
    ready: dict[str, str], outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    outside.write("design.md", b"# Design\n\nA file.\n")
    d: str = digest(neo4j_settings)

    failed = run_noesis(
        ["import", "file", str(outside.root / "design.md"), "--subtype", "Big Kind"], ready
    )

    error = error_of(failed)
    assert error["code"] == "IMPORT_203_FILE_NOT_IMPORTABLE"
    assert error["metadata"]["reason"] == "invalid_metadata"
    assert error["metadata"]["detail"] == "KNOWLEDGE_002_INVALID_SLUG"
    assert digest(neo4j_settings) == d


def test_a_closed_note_without_a_ulid_is_found_by_locator_and_never_duplicated(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    id8: str = str(rows(apply(ready))[N8]["record_id"])
    with graph_session(neo4j_settings) as session:
        seed_status(session, id8, "retracted")

    again = apply(ready)
    vault.append(N8, "More.\n")
    changed = apply(ready)
    blocked = apply(ready, "--update")

    assert (rows(again)[N8]["outcome"], rows(again)[N8]["record_id"]) == ("unchanged", id8)
    assert rows(changed)[N8]["outcome"] == "changed_in_vault"
    assert (rows(blocked)[N8]["outcome"], rows(blocked)[N8]["reason"]) == (
        "blocked",
        "target_closed",
    )
    assert knowledge_count(neo4j_settings) == 7


def supersedes_about(env: dict[str, str], record_id: str) -> list[dict[str, Any]]:
    """`assertion list --about <id> --role object --predicate supersedes`: the items."""
    listed = run_noesis(
        [
            "assertion",
            "list",
            "--about",
            record_id,
            "--role",
            "object",
            "--predicate",
            "supersedes",
        ],
        env,
    )
    assert listed.code == 0, listed.stdout
    return list(listed.result["assertions"])  # type: ignore[call-overload]


def test_ac023b_accepted_note_gets_a_linked_successor(
    ready: dict[str, str], vault: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    assert apply(ready).code == 0
    with graph_session(neo4j_settings) as session:
        seed_status(session, K5, "accepted")
    vault.append(N5, "Also fast.\n")

    linked = apply(ready, "--update")

    assert linked.code == 0, linked.stdout
    row = rows(linked)[N5]
    assert row["outcome"] == "successor_proposed"
    successor: str = row["record_id"]
    assertion_id: str = row["assertion_id"]
    assert successor not in (None, K5) and assertion_id is not None
    assert row["target_record_id"] == K5
    assert record(ready, successor)["status"] == "proposed"
    assert (record(ready, K5)["status"], record(ready, K5)["head_revision"]) == ("accepted", 1)
    [assertion] = supersedes_about(ready, K5)
    assert (
        assertion["id"],
        assertion["status"],
        assertion["subject"]["id"],
        assertion["object"]["id"],
    ) == (assertion_id, "proposed", successor, K5)

    rerun = apply(ready, "--update")

    assert (rows(rerun)[N5]["outcome"], rows(rerun)[N5]["record_id"]) == ("unchanged", successor)
    assert len(supersedes_about(ready, K5)) == 1


def test_ac026b_import_file_on_an_accepted_record_proposes_a_linked_successor(
    tmp_path: Path, outside: Folder, neo4j_settings: Neo4jConnectionSettings
) -> None:
    env = child_env(tmp_path, neo4j_settings, None)
    assert run_noesis(["store", "init"], env).code == 0
    outside.write("design.md", DESIGN)
    command = [
        "import",
        "file",
        str(outside.root / "design.md"),
        "--title",
        "Design notes",
        "--project",
        "alpha",
        "--tag",
        "area:core",
    ]
    first = run_noesis(command, env)
    assert first.code == 0, first.stdout
    target_id = str(first.result["record_id"])
    with graph_session(neo4j_settings) as session:
        seed_status(session, target_id, "accepted")
    outside.append("design.md", "More.\n")

    second = run_noesis(command, env)

    assert second.code == 0, second.stdout
    assert second.result["outcome"] == "successor_proposed"
    successor = str(second.result["record_id"])
    assert successor != target_id and second.result["target_record_id"] == target_id
    assertion_id = second.result["assertion_id"]
    assert assertion_id is not None
    [assertion] = supersedes_about(env, target_id)
    assert (assertion["id"], assertion["subject"]["id"], assertion["status"]) == (
        assertion_id,
        successor,
        "proposed",
    )
    assert assertion["applicability"]["project_key"] == "alpha"
    assert record(env, target_id)["status"] == "accepted"
    with graph_session(neo4j_settings) as session:
        sources = session.run("MATCH (s:Source) RETURN count(s) AS c").single()
    assert sources is not None and sources["c"] == 2  # one file_version per digest, none added

    third = run_noesis(command, env)

    assert (third.result["outcome"], third.result["record_id"]) == ("unchanged", successor)
    assert len(supersedes_about(env, target_id)) == 1
