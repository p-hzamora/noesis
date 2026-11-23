"""The discovery benchmark: fixture loading, world building, searching and the metrics (NFR-004, NFR-005).

The content is generic and lives in `tests/fixtures/discovery/`: `skills/<name>/SKILL.md`,
`runtimes.yaml`, `records.yaml` and `tasks.yaml`. No real user data.
"""

import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml
from tests.support.catalog_process_support import CatalogWorld, install_claude_plugin, run_catalog
from tests.support.review_commands import USER, accept_knowledge_command
from tests.support.review_support import ReviewNeo4jEnv, run_with_handlers

from noesis.bounded_context.knowledge.domain.value_objects import AssertionPredicateEnum, RecordId
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

FIXTURE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"
REPORT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / ".measurement" / "discovery-benchmark.json"
)
BULK_PLUGIN: Final[str] = "bulk-suite"
RUNTIMES: Final[tuple[str, ...]] = ("claude-code", "codex")
SEARCH_ACTIONS: Final[frozenset[str]] = frozenset(
    {"load_skill", "use_agent", "use_cli_tool", "use_mcp_server", "read_record"}
)


@dataclass(frozen=True, slots=True)
class Task:
    """One benchmark task: what the agent asks and what a correct answer holds."""

    id: str
    task: str
    needs: tuple[str, ...]
    expected_resources: tuple[str, ...]
    optional_resources: tuple[str, ...]
    expected_load_order: tuple[tuple[str, str], ...]
    expected_missing: tuple[str, ...]
    forbidden_records: tuple[str, ...]
    expected_endorsement: Mapping[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Search:
    """One `noesis search` process and what it answered."""

    result: dict[str, Any]
    json_bytes: int
    seconds: float


def _load(name: str) -> dict[str, Any]:
    loaded: object = yaml.safe_load((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def load_tasks() -> list[Task]:
    """The tasks of `tasks.yaml`; the golden task is the first."""
    return [
        Task(
            id=raw["id"],
            task=raw["task"],
            needs=tuple(raw["needs"]),
            expected_resources=tuple(raw["expected_resources"]),
            optional_resources=tuple(raw.get("optional_resources", ())),
            expected_load_order=tuple((a, b) for a, b in raw["expected_load_order"]),
            expected_missing=tuple(raw["expected_missing"]),
            forbidden_records=tuple(raw["forbidden_records"]),
            expected_endorsement=raw.get("expected_endorsement", {}),
        )
        for raw in _load("tasks.yaml")["tasks"]
    ]


def known_resource_names() -> set[str]:
    """Every resource name that exists in the fixture world: installed skills and catalog entries."""
    runtimes: dict[str, Any] = _load("runtimes.yaml")
    installed: set[str] = {
        f"{plugin['plugin']}:{skill}"
        for spec in runtimes.values()
        for plugin in spec["plugins"]
        for skill in plugin["skills"]
    }
    return installed | {entry["name"] for entry in _load("records.yaml")["catalog_entries"]}


def install_runtimes(world: CatalogWorld, *, bulk_skills: int = 0) -> None:
    """Install the fake Claude Code and Codex runtimes into `world`, plus `bulk_skills` filler skills."""
    for runtime, spec in _load("runtimes.yaml").items():
        for plugin in spec["plugins"]:
            name: str = plugin["plugin"]
            if runtime == "claude-code":
                root: Path = install_claude_plugin(
                    world, name, plugin["marketplace"], plugin["version"]
                )
            else:
                config: Path = world.codex_dir / "config.toml"
                config.write_text(
                    f'{config.read_text(encoding="utf-8")}[plugins."{name}@{plugin["marketplace"]}"]\n',
                    encoding="utf-8",
                )
                root = (
                    world.codex_dir
                    / "plugins/cache"
                    / plugin["marketplace"]
                    / name
                    / plugin["version"]
                )
            for skill in plugin["skills"]:
                _write(
                    root / "skills" / skill / "SKILL.md",
                    (FIXTURE_DIR / "skills" / skill / "SKILL.md").read_text("utf-8"),
                )
    if bulk_skills:
        root = install_claude_plugin(world, BULK_PLUGIN, "market", "1.0")
        for number in range(bulk_skills):
            label: str = f"filler-{number:03d}"
            _write(
                root / "skills" / label / "SKILL.md",
                f"---\nname: {label}\ndescription: Unrelated filler skill {number} for audio mixing\n---\n# {label}\n",
            )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def seed_store(
    world: CatalogWorld, env: dict[str, str], settings: Neo4jConnectionSettings
) -> dict[str, str]:
    """`store init`, then records, relations, catalog entries and `recommends`; returns key -> record id.

    Records and assertions go through the real handlers (capture, accept as the user, propose);
    catalog entries go through `catalog register`.
    """
    assert run_catalog(world, ["store", "init"], env).code == 0
    spec: dict[str, Any] = _load("records.yaml")

    async def seed_records(handlers: ReviewNeo4jEnv) -> dict[str, RecordId]:
        ids: dict[str, RecordId] = {}
        for raw in spec["records"]:
            record_id: RecordId = await handlers.capture(
                f"seed-{raw['key']}", project=raw["project"], title=raw["title"], body=raw["body"]
            )
            ids[raw["key"]] = record_id
            if raw["status"] == "accepted":
                await handlers.accept_knowledge().handle(
                    accept_knowledge_command(record_id, f"accept-{raw['key']}", actor=USER)
                )
        return ids

    ids: dict[str, RecordId] = run_with_handlers(settings, seed_records)
    catalog_ids: dict[str, RecordId] = {}
    for entry in spec["catalog_entries"]:
        registered: dict[str, object] = run_catalog(
            world,
            [
                "catalog",
                "register",
                "--kind",
                entry["kind"],
                "--name",
                entry["name"],
                "--purpose",
                entry["purpose"],
                "--location",
                entry["location"],
                "--source",
                f"url:{entry['location']}",
                "--idempotency-key",
                f"register-{entry['name']}",
            ],
            env,
        ).result
        catalog_ids[entry["name"]] = RecordId(value=str(registered["id"]))

    async def seed_relations(handlers: ReviewNeo4jEnv) -> None:
        for relation in spec["relations"]:
            predicate = AssertionPredicateEnum(relation["predicate"])
            subject, target = ids[relation["subject"]], ids[relation["object"]]
            key: str = f"rel-{relation['subject']}-{relation['object']}"
            if relation["accepted"]:
                await handlers.seed_accepted_assertion(predicate, subject, target, key)
            else:
                await handlers.propose(predicate, subject, target, key)
        for raw in spec["recommends"]:
            await handlers.seed_accepted_assertion(
                AssertionPredicateEnum.RECOMMENDS,
                ids[raw["subject"]],
                catalog_ids[raw["object"]],
                f"recommends-{raw['subject']}-{raw['object']}",
            )

    run_with_handlers(settings, seed_relations)
    return {key: value.value for key, value in ids.items()}


def search(
    world: CatalogWorld,
    env: dict[str, str],
    query: str,
    target_root: Path,
    *,
    needs: Sequence[str] = (),
    resources: bool = True,
) -> Search:
    """One `noesis search` for a new `target_root`, over both fake runtimes."""
    argv: list[str] = ["search", query, "--target-root", str(target_root)]
    for runtime in RUNTIMES:
        argv += ["--runtime", runtime]
    for need in needs:
        argv += ["--need", need]
    if not resources:
        argv.append("--no-resources")
    started: float = time.perf_counter()
    found = run_catalog(world, argv, env)
    seconds: float = time.perf_counter() - started
    assert found.code == 0, (found.stdout, found.stderr)
    return Search(
        result=found.result, json_bytes=len(found.stdout.encode("utf-8")), seconds=seconds
    )


def p95(samples: Sequence[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered: list[float] = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def short_name(resource: Mapping[str, Any]) -> str:
    """`design-suite:cli-interface` for a resource whose ref is `catalog:skill:design-suite:cli-interface`."""
    return str(resource["name"])


def task_metrics(task: Task, answer: Search, record_keys: Mapping[str, str]) -> dict[str, Any]:
    """Everything the benchmark measures for one task and one answer (the definitions of NFR-005).

    - `covered_needs` / `expected_covered_needs`: needs reported `covered`, over needs that should be.
    - `hallucinated`: returned resources that exist nowhere in the fixture world, plus resources
      supporting a need that is expected missing, plus a missing need not reported `missing`.
    - `precision_at_k`: share of the first k resources (k = expected count) that are expected or optional.
    - `redundant`: returned resources that are neither expected nor optional, plus duplicate refs.
    - `forbidden_records`: forbidden record keys returned as current (not labelled `superseded`).
    - `load_order_violations`: expected (before, after) pairs, both returned, in the wrong order.
    """
    result: dict[str, Any] = answer.result
    resources: list[dict[str, Any]] = sorted(
        result["resources"], key=lambda item: item["load_order"]
    )
    names: list[str] = [short_name(item) for item in resources]
    relevant: set[str] = {*task.expected_resources, *task.optional_resources}
    coverage: dict[str, str] = {item["id"]: item["coverage"] for item in result["requirements"]}
    expected_covered: list[str] = [need for need in task.needs if need not in task.expected_missing]
    hallucinated: list[str] = [name for name in names if name not in known_resource_names()]
    for need in task.expected_missing:
        supporting: list[str] = [
            ref
            for item in result["requirements"]
            if item["id"] == need
            for ref in item["supported_by"]
        ]
        if coverage.get(need) != "missing" or supporting:
            hallucinated.append(f"need:{need}")
    k: int = len(task.expected_resources)
    forbidden_ids: dict[str, str] = {record_keys[key]: key for key in task.forbidden_records}
    forbidden: list[str] = [
        forbidden_ids[hit["id"]]
        for hit in result["hits"]
        if hit["id"] in forbidden_ids and hit["authority"] != "superseded"
    ]
    position: dict[str, int] = {name: index for index, name in enumerate(names)}
    violations: list[str] = [
        f"{before}<{after}"
        for before, after in task.expected_load_order
        if before in position and after in position and position[before] > position[after]
    ]
    endorsement: dict[str, str] = {item["name"]: item["endorsement"] for item in resources}
    contradicted: list[str] = [
        hit["title"]
        for hit in result["hits"]
        if hit["id"] == record_keys["cli-argv-by-hand"] and hit["authority"] == "authoritative"
    ]
    return {
        "task": task.id,
        "returned": names,
        "covered_needs": sum(1 for need in expected_covered if coverage.get(need) == "covered"),
        "expected_covered_needs": len(expected_covered),
        "missing_reported": sorted(need for need, value in coverage.items() if value == "missing"),
        "missing_expected": sorted(task.expected_missing),
        "absent_expected_resources": sorted(set(task.expected_resources) - set(names)),
        "hallucinated": hallucinated,
        "precision_at_k": (
            sum(1 for name in names[:k] if name in relevant) / k if k else float(not names)
        ),
        "redundant": [name for name in names if name not in relevant]
        + [n for n in set(names) if names.count(n) > 1],
        "returned_count": len(names),
        "forbidden_records": forbidden,
        "load_order_violations": violations,
        "endorsement_mismatches": [
            name
            for name, wanted in task.expected_endorsement.items()
            if endorsement.get(name) != wanted
        ],
        "invalid_actions": [
            step["action"]
            for step in result["next_actions"]
            if step["action"] not in SEARCH_ACTIONS
        ],
        "contradicted_authoritative_hits": contradicted,
        "json_bytes": answer.json_bytes,
        "latency_seconds": round(answer.seconds, 3),
        "cataloged": sorted({bool(item["cataloged"]) for item in resources}),
    }


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    """Roll per-task metrics up to the numbers NFR-005 thresholds."""
    expected: int = sum(row["expected_covered_needs"] for row in rows)
    returned: int = sum(row["returned_count"] for row in rows)
    return {
        "requirement_coverage": sum(row["covered_needs"] for row in rows) / expected,
        "precision_at_k": sum(row["precision_at_k"] for row in rows) / len(rows),
        "redundancy": sum(len(row["redundant"]) for row in rows) / returned if returned else 0.0,
        "hallucinated_resources": sum(len(row["hallucinated"]) for row in rows),
        "forbidden_records": sum(len(row["forbidden_records"]) for row in rows),
        "load_order_violations": sum(len(row["load_order_violations"]) for row in rows),
        "endorsement_mismatches": sum(len(row["endorsement_mismatches"]) for row in rows),
        "absent_expected_resources": sum(len(row["absent_expected_resources"]) for row in rows),
        "contradicted_authoritative_hits": sum(
            len(row["contradicted_authoritative_hits"]) for row in rows
        ),
        "json_bytes_mean": sum(row["json_bytes"] for row in rows) / len(rows),
        "latency_seconds_mean": sum(row["latency_seconds"] for row in rows) / len(rows),
        "searches": len(rows),
    }


def write_report(section: str, payload: Mapping[str, Any]) -> Path:
    """Merge `payload` under `section` into the JSON report (`.measurement/`, git-ignored)."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = (
        json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    )
    report[section] = payload
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return REPORT_PATH
