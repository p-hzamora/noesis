"""NFR-005 harness: preview, apply and a second apply against a copy of a real vault.

Not a test of behaviour: it measures. The source vault is only read (a snapshot before and after)
and copied with `shutil.copytree` into `tmp_path`; every command runs against the copy. Hard
checks: the source and the copy are unchanged, the preview adds up and predicts the first apply,
the second apply writes nothing. Wall times and `totals.blocked` are recorded, never asserted.
The JSON report holds counts and paths only, no note text.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from tests.support.import_support import file_snapshot
from tests.support.noesis_process_support import ProcessResult, run_noesis, store_environment

from noesis.bounded_context.interop.domain.services import TextNormaliser
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.measurement, pytest.mark.integration, pytest.mark.neo4j]

VAULT_KEY = "measured"
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+.*)?$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _body_of(data: bytes) -> str | None:
    """The body of a note (header dropped, LF newlines), or None when it is not usable text."""
    try:
        text: str = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = text.split("\n")
    if lines and lines[0] == "---":
        for index in range(1, len(lines)):
            if re.fullmatch(r"---[ \t]*", lines[index]):
                return "\n".join(lines[index + 1 :])
        return None
    return text


def _headings(body: str) -> int:
    """ATX headings outside fenced blocks."""
    count: int = 0
    fence: str | None = None
    for line in body.split("\n"):
        opening = FENCE.match(line)
        if fence is None and opening:
            fence = opening.group(1)[0]
        elif fence is not None and re.match(rf"^ {{0,3}}{re.escape(fence)}{{3,}}[ \t]*$", line):
            fence = None
        elif fence is None and HEADING.match(line):
            count += 1
    return count


def _text_figures(root: Path) -> dict[str, int]:
    """Raw versus stored body characters and removed sections, computed with `TextNormaliser`."""
    normaliser = TextNormaliser()
    raw = stored = removed = 0
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
            continue
        body = _body_of(path.read_bytes())
        if body is None:
            continue
        normalised = normaliser.normalise(body)
        raw += len(body)
        stored += len(normalised)
        removed += max(_headings(body) - _headings(normalised), 0)
    return {
        "raw_body_characters": raw,
        "stored_body_characters": stored,
        "sections_removed": removed,
    }


def _summary(run: ProcessResult) -> dict[str, Any]:
    result: dict[str, Any] = run.result
    return {
        "seconds": round(run.seconds, 3),
        "applied": result["applied"],
        "complete": result["complete"],
        "totals": result["totals"],
        "blocked_reasons": result["blocked_reasons"],
        "warnings": result["warnings"],
        "sources_skipped": result["sources_skipped"],
    }


def test_nfr005_import_run_against_a_copy_of_the_real_vault(
    vault_source: Path,
    tmp_path: Path,
    neo4j_settings: Neo4jConnectionSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_before = file_snapshot(vault_source)
    copy: Path = tmp_path / "vault-copy"
    shutil.copytree(vault_source, copy, symlinks=True)
    copy_before = file_snapshot(copy)
    env = store_environment(
        tmp_path / "child-home",
        "personal",
        neo4j_settings,
        NOESIS_VAULT_DIR=str(copy),
        NOESIS_IMPORT_VAULT_KEY=VAULT_KEY,
    )
    assert run_noesis(["store", "init"], env).code == 0

    first_preview = run_noesis(["import", "run", "--verbose"], env)
    first_apply = run_noesis(["import", "run", "--yes", "--verbose"], env)
    second_apply = run_noesis(["import", "run", "--yes", "--verbose"], env)

    report: dict[str, Any] = {
        "notes": first_preview.result["totals"]["notes"],
        "preview": _summary(first_preview),
        "apply": _summary(first_apply),
        "second_apply": _summary(second_apply),
        **_text_figures(copy),
        "source_vault_unchanged": file_snapshot(vault_source) == source_before,
        "copy_vault_unchanged": file_snapshot(copy) == copy_before,
        "blocked_paths": sorted(
            row["path"]
            for row in first_apply.result["notes"]
            if row["outcome"] == "blocked"  # type: ignore[union-attr]
        ),
    }
    report_path: Path = tmp_path / "import-measurement-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with capsys.disabled():
        print(f"\nNFR-005 report: {report_path}")  # noqa: T201 - the harness reports where it wrote
        print(json.dumps({k: v for k, v in report.items() if k != "blocked_paths"}, indent=2))  # noqa: T201

    assert report["source_vault_unchanged"] is True
    assert report["copy_vault_unchanged"] is True
    for run in (first_preview, first_apply, second_apply):
        totals: dict[str, int] = run.result["totals"]  # type: ignore[assignment]
        assert sum(value for key, value in totals.items() if key != "notes") == totals["notes"]
    preview_rows = {r["path"]: r["outcome"] for r in first_preview.result["notes"]}  # type: ignore[union-attr]
    apply_rows = {r["path"]: r["outcome"] for r in first_apply.result["notes"]}  # type: ignore[union-attr]
    assert preview_rows == apply_rows
    assert all(
        row["outcome"] in ("unchanged", "skipped_empty", "blocked")
        for row in second_apply.result["notes"]  # type: ignore[union-attr]
    )
    assert second_apply.result["totals"]["blocked"] == first_apply.result["totals"]["blocked"]  # type: ignore[index]
