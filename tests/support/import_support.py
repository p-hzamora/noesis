"""Helpers of the import (C3) tests: the fixture vault, snapshots and raw-graph inspection.

Nothing here reads the user's vault or the user's `NOESIS_*` settings: every vault is a copy of
`tests/fixtures/vault_import/` under a test's `tmp_path` (NFR-001).
"""

import base64
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from neo4j import Session
from tests.support.neo4j_container import admin_driver

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

FIXTURE_VAULT: Final[Path] = Path(__file__).resolve().parents[1] / "fixtures" / "vault_import"
EXPECTED_BODIES: Final[Path] = (
    Path(__file__).resolve().parents[1] / "fixtures" / "vault_import_expected"
)

C1SHA: Final[str] = "c1" * 20
"""The one commit sha every current-layout fixture header cites in `noesis.sources`."""

K1, K2, K3, K4, K5, K6, K7, K8, K9, K10 = (f"01JCKMNP{n:018d}" for n in range(1, 11))
"""Valid ULIDs (first character 0-7, Crockford alphabet, 26 characters) used by the fixture."""

VAULT_KEY: Final[str] = "fixture"

N1: Final[str] = "repos/alpha/concepts/ports.md"
N2: Final[str] = "repos/alpha/howtos/capture.md"
N3: Final[str] = "learning/python/concepts/diseño-hexagonal.md"
N4: Final[str] = "repos/alpha/runs/2026-11-01-import-trial.md"
N5: Final[str] = "repos/alpha/decisions/use-neo4j.md"
N6: Final[str] = "learning/python/index.md"
N7: Final[str] = "learning/python/legacy-note.md"
N8: Final[str] = "README.md"
N9: Final[str] = "repos/beta/gotchas/empty.md"
N10: Final[str] = "misc/zero.md"
N11: Final[str] = "inbox/bad-id.md"
N12: Final[str] = "inbox/dup-a.md"
N13: Final[str] = "inbox/dup-b.md"
N14: Final[str] = "inbox/broken-header.md"
N15: Final[str] = "inbox/binary.md"
N16: Final[str] = "inbox/bad-scope.md"
N17: Final[str] = "inbox/bad-kind.md"

ONE_PIXEL_PNG: Final[bytes] = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

CLEAN_TOTALS: Final[dict[str, int]] = {
    "notes": 10,
    "created": 7,
    "unchanged": 0,
    "changed_in_vault": 0,
    "revised": 0,
    "successor_proposed": 0,
    "skipped_empty": 3,
    "blocked": 0,
}
FULL_TOTALS: Final[dict[str, int]] = {**CLEAN_TOTALS, "notes": 17, "blocked": 7}
FULL_BLOCKED_REASONS: Final[dict[str, int]] = {
    "invalid_id": 1,
    "duplicate_id": 2,
    "invalid_header": 1,
    "not_text": 1,
    "invalid_scope": 1,
    "invalid_metadata": 1,
}


def copy_fixture_vault(tmp_path: Path, *, clean: bool = True, name: str = "vault") -> Path:
    """Copy the fixture vault to `tmp_path/<name>` and add what git cannot hold reliably.

    Args:
        tmp_path: The test's folder.
        clean: Drop `inbox/` (the clean fixture); when false, also create `inbox/binary.md`.
        name: Folder name of the copy (the default vault key when no key is configured).

    Returns:
        The copy's root.
    """
    root: Path = tmp_path / name
    shutil.copytree(
        FIXTURE_VAULT,
        root,
        ignore=shutil.ignore_patterns("inbox") if clean else None,
        symlinks=True,
    )
    (root / "misc").mkdir()
    (root / "misc" / "zero.md").write_bytes(b"")
    (root / "assets").mkdir()
    (root / "assets" / "diagram.png").write_bytes(ONE_PIXEL_PNG)
    (root / "repos/alpha/linked.md").symlink_to("concepts/ports.md")
    if not clean:
        (root / "inbox").mkdir(exist_ok=True)
        (root / "inbox" / "binary.md").write_bytes(b"\xff\xfe\x00\x01")
    return root


def file_snapshot(root: Path) -> dict[str, tuple[str, str, int]]:
    """Every entry under `root` (hidden ones included), read without following links.

    Returns:
        Relative path -> (kind `file|dir|link`, sha256 of the bytes or of the link target text
        (empty for a directory), `st_mtime_ns`).
    """
    entries: dict[str, tuple[str, str, int]] = {}

    def visit(folder: Path) -> None:
        with os.scandir(folder) as scan:
            for entry in sorted(scan, key=lambda item: item.name):
                path: Path = Path(entry.path)
                info: os.stat_result = os.lstat(path)
                relative: str = path.relative_to(root).as_posix()
                if stat.S_ISLNK(info.st_mode):
                    digest: str = hashlib.sha256(str(path.readlink()).encode()).hexdigest()
                    entries[relative] = ("link", digest, info.st_mtime_ns)
                elif stat.S_ISDIR(info.st_mode):
                    entries[relative] = ("dir", "", info.st_mtime_ns)
                    visit(path)
                else:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    entries[relative] = ("file", digest, info.st_mtime_ns)

    visit(root)
    return entries


@contextmanager
def graph_session(settings: Neo4jConnectionSettings) -> Iterator[Session]:
    """A synchronous session on the test container for inspection and seeding."""
    with admin_driver(settings) as driver, driver.session(database=settings.database) as session:
        yield session


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def graph_digest(session: Session) -> str:
    """`sha256` over every node (labels, properties) and relationship (type, ends, properties)."""
    nodes: list[str] = [
        _canonical([sorted(row["labels"]), row["props"]])
        for row in session.run(
            "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"
        ).data()
    ]
    relationships: list[str] = [
        _canonical([row["type"], row["start"], row["end"], row["props"]])
        for row in session.run(
            "MATCH (a)-[r]->(b) RETURN type(r) AS type, properties(a) AS start, "
            "properties(b) AS end, properties(r) AS props"
        ).data()
    ]
    payload: str = _canonical([sorted(nodes), sorted(relationships)])
    return hashlib.sha256(payload.encode()).hexdigest()


def graph_counts(session: Session) -> dict[str, Any]:
    """Nodes per label, relationships per type, `:Revision` and `:IdempotencyKey` counts."""
    labels: dict[str, int] = {
        row["label"]: row["total"]
        for row in session.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS total"
        ).data()
    }
    types: dict[str, int] = {
        row["type"]: row["total"]
        for row in session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS total").data()
    }
    return {
        "labels": labels,
        "relationships": types,
        "revisions": labels.get("Revision", 0),
        "idempotency_keys": labels.get("IdempotencyKey", 0),
    }


def seed_status(session: Session, record_id: str, status: str) -> None:
    """Set a Knowledge record's stored status (C2 has no transition and C4 may not exist)."""
    session.run(
        "MATCH (k:Knowledge {id: $id}) SET k.status = $status", id=record_id, status=status
    ).consume()


def seed_node(session: Session, labels: list[str], record_id: str, space_id: str) -> None:
    """Create a bare `:Record:<label>` node, to make an id taken by another record type."""
    allowed: set[str] = {"Experience", "Project", "Source", "Assertion", "Knowledge"}
    assert set(labels) <= allowed, labels
    label_clause: str = "".join(f":{label}" for label in labels)
    session.run(
        f"CREATE (n:Record{label_clause} {{id: $id, space_id: $space_id}})",
        id=record_id,
        space_id=space_id,
    ).consume()


def knowledge_by_locator(session: Session, locator: str) -> list[str]:
    """Ids of Knowledge records citing a `file_version` Source with `locator`."""
    rows: list[dict[str, Any]] = session.run(
        "MATCH (:Source {kind: 'file_version', locator: $locator})<-[:FROM_SOURCE]-(:Revision)"
        "-[:REVISION_OF]->(k:Knowledge) RETURN DISTINCT k.id AS id ORDER BY id",
        locator=locator,
    ).data()
    return [row["id"] for row in rows]


def space_id_of(session: Session, key: str) -> str:
    """Id of the space with `key`."""
    rows: list[dict[str, Any]] = session.run(
        "MATCH (s:Space {key: $key}) RETURN s.id AS id", key=key
    ).data()
    assert len(rows) == 1, rows
    return str(rows[0]["id"])


def ledger_keys(session: Session) -> list[str]:
    """Every idempotency key recorded in the ledger (without the space prefix), sorted."""
    rows: list[dict[str, Any]] = session.run(
        "MATCH (e:IdempotencyKey) RETURN e.idempotency_key AS key ORDER BY key"
    ).data()
    return [str(row["key"]) for row in rows]


def expected_body(name: str) -> str:
    """The stored body `name` (`B1`, `B2`, `B5`) from `tests/fixtures/vault_import_expected/`.

    The stored body has no trailing newline (normaliser output); one final newline that an
    editor may have added to the `.txt` file is the only thing removed.
    """
    text: str = (EXPECTED_BODIES / f"{name}.txt").read_text(encoding="utf-8")
    return text.removesuffix("\n")
