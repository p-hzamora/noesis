"""Loads the hand-authored retrieval fixtures (records and graded queries) from `tests/fixtures`."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

FIXTURE_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "retrieval"
RECORD_FILES: Final[tuple[str, ...]] = ("records_en.json", "records_es.json", "records_other.json")
SLICES: Final[tuple[str, ...]] = ("en-en", "es-es", "es-en", "en-es", "identifier", "none")
SHARED_SOURCE_NUMBERS: Final[frozenset[int]] = frozenset({1, 2})


@dataclass(frozen=True, slots=True)
class FixtureRecord:
    """One fixture record; `key` is its stable fixture key (`E01.1`)."""

    key: str
    cluster: str
    kind: str  # "knowledge" | "experience"
    subtype: str
    status: str | None  # knowledge only; the target status (capture always starts `proposed`)
    project: str | None
    lang: str
    title: str | None
    body: str
    source_locator: str = field(default="")


@dataclass(frozen=True, slots=True)
class FixtureQuery:
    """One query with graded judgments by fixture key (3 direct, 2 strong, 1 tangential)."""

    id: str
    slice: str
    text: str
    relevance: dict[str, int]
    project: str | None


def _locator(group: str) -> str:
    """A stable 40-hex commit locator for a source group (records of one group share it)."""
    return hashlib.sha1(f"spike-source:{group}".encode(), usedforsecurity=False).hexdigest()


def load_records() -> list[FixtureRecord]:
    """Every fixture record, in file order. Records 1 and 2 of a cluster share one commit source."""
    records: list[FixtureRecord] = []
    for name in RECORD_FILES:
        document = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        for cluster in document["clusters"]:
            for raw in cluster["records"]:
                key = f"{cluster['id']}.{raw['n']}"
                group = cluster["id"] if raw["n"] in SHARED_SOURCE_NUMBERS else key
                is_knowledge = raw["t"] == "k"
                records.append(
                    FixtureRecord(
                        key=key,
                        cluster=cluster["id"],
                        kind="knowledge" if is_knowledge else "experience",
                        subtype=raw["sub"],
                        status=raw.get("st") if is_knowledge else None,
                        project=cluster["project"],
                        lang=raw.get("lang", cluster["lang"]),
                        title=raw.get("title") if is_knowledge else None,
                        body=raw["body"],
                        source_locator=_locator(group),
                    )
                )
    return records


def load_queries() -> list[FixtureQuery]:
    """Every graded query."""
    document = json.loads((FIXTURE_DIR / "queries.json").read_text(encoding="utf-8"))
    return [
        FixtureQuery(
            id=raw["id"],
            slice=raw["slice"],
            text=raw["text"],
            relevance=dict(raw["rel"]),
            project=raw.get("project"),
        )
        for raw in document["queries"]
    ]
