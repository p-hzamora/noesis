"""Discovery benchmark (WP-27, WP-28; AC-024): NFR-005 quality thresholds and NFR-004 overlay latency.

The quality benchmark runs in the default suite: it needs no vault, only the Neo4j container every
`neo4j` test uses. The latency benchmark (100 sequential processes) is slower and only runs with
`--discovery-latency`:

    uv run pytest tests/measurement/test_discovery_benchmark.py --discovery-latency

Both merge their metrics into `.measurement/discovery-benchmark.json` (git-ignored).
"""

from pathlib import Path
from typing import Any

import pytest
from tests.support.catalog_process_support import (
    CatalogWorld,
    make_world,
    run_catalog,
    world_environment,
)
from tests.support.discovery_benchmark_support import (
    Task,
    aggregate,
    install_runtimes,
    load_tasks,
    p95,
    search,
    seed_store,
    task_metrics,
    write_report,
)
from tests.support.retrieval.retrieval_process_support import ACTIVE_SPACE

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

MIN_REQUIREMENT_COVERAGE = 0.9
MAX_OVERLAY_LATENCY_RATIO = 1.5
OVERLAY_RUNS = 50
OVERLAY_SKILLS = 100
GOLDEN_TASK = (
    "Create a brand-new project at ~/Desktop/new-test-project, using uv, implemented as a "
    "Python CLI, and following my DDD conventions."
)


def _scenario(
    tmp_path: Path, settings: Neo4jConnectionSettings, *, bulk_skills: int = 0
) -> tuple[CatalogWorld, dict[str, str], dict[str, str]]:
    world: CatalogWorld = make_world(tmp_path / "world")
    env: dict[str, str] = world_environment(world, settings, space=ACTIVE_SPACE)
    install_runtimes(world, bulk_skills=bulk_skills)
    return world, env, seed_store(world, env, settings)


def _run_tasks(
    world: CatalogWorld,
    env: dict[str, str],
    keys: dict[str, str],
    tasks: list[Task],
    target: Path,
) -> list[dict[str, Any]]:
    """Each task with resources, and its record-only baseline (today's lexical search)."""
    rows: list[dict[str, Any]] = []
    for task in tasks:
        row: dict[str, Any] = task_metrics(
            task, search(world, env, task.task, target, needs=task.needs), keys
        )
        baseline = search(world, env, task.task, target, resources=False)
        row["baseline_json_bytes"] = baseline.json_bytes
        row["baseline_latency_seconds"] = round(baseline.seconds, 3)
        rows.append(row)
    return rows


def test_discovery_benchmark_thresholds(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings
) -> None:
    """NFR-005: coverage >= 0.9, no hallucinated resource, no forbidden record, cold start and synced."""
    tasks: list[Task] = load_tasks()
    assert tasks[0].task == GOLDEN_TASK
    world, env, keys = _scenario(tmp_path, neo4j_settings)
    target: Path = tmp_path / "new-test-project"

    cold: list[dict[str, Any]] = _run_tasks(world, env, keys, tasks, target)
    synced_run = run_catalog(world, ["catalog", "sync"], env)
    assert synced_run.code == 0, (synced_run.stdout, synced_run.stderr)
    synced: list[dict[str, Any]] = _run_tasks(world, env, keys, tasks, target)

    scenarios: dict[str, list[dict[str, Any]]] = {"cold_start": cold, "after_sync": synced}
    summary: dict[str, dict[str, float | int]] = {
        name: aggregate(rows) for name, rows in scenarios.items()
    }
    path: Path = write_report(
        "quality",
        {
            "thresholds": {"requirement_coverage_min": MIN_REQUIREMENT_COVERAGE},
            "queries_per_search": "not observable from the CLI; one noesis process per search",
            "summary": summary,
            "tasks": scenarios,
        },
    )

    assert path.is_file()
    for name, totals in summary.items():
        assert totals["requirement_coverage"] >= MIN_REQUIREMENT_COVERAGE, name
        assert totals["hallucinated_resources"] == 0, name
        assert totals["forbidden_records"] == 0, name
        assert totals["load_order_violations"] == 0, name
        assert totals["endorsement_mismatches"] == 0, name
    assert all(False not in row["cataloged"] for row in synced), (
        "after `catalog sync` every returned resource is cataloged"
    )
    assert any(False in row["cataloged"] for row in cold), (
        "cold start finds skills from the overlay"
    )


def test_overlay_latency_ratio(
    tmp_path: Path, neo4j_settings: Neo4jConnectionSettings, discovery_latency: None
) -> None:
    """NFR-004: p95 over 50 runs with the live overlay on 100 unsynced skills <= 1.5x record-only."""
    world, env, _ = _scenario(tmp_path, neo4j_settings, bulk_skills=OVERLAY_SKILLS)
    target: Path = tmp_path / "new-test-project"
    needs: tuple[str, ...] = ("scaffold", "python-ddd", "cli", "uv")
    search(world, env, GOLDEN_TASK, target, resources=False)  # warm the store and the import cache
    search(world, env, GOLDEN_TASK, target, needs=needs)

    record_only: list[float] = []
    with_overlay: list[float] = []
    for _ in range(OVERLAY_RUNS):  # interleaved, so drift hits both equally
        record_only.append(search(world, env, GOLDEN_TASK, target, resources=False).seconds)
        with_overlay.append(search(world, env, GOLDEN_TASK, target, needs=needs).seconds)
    ratio: float = p95(with_overlay) / p95(record_only)
    write_report(
        "overlay_latency",
        {
            "runs": OVERLAY_RUNS,
            "skills": OVERLAY_SKILLS,
            "p95_record_only_seconds": round(p95(record_only), 3),
            "p95_with_overlay_seconds": round(p95(with_overlay), 3),
            "ratio": round(ratio, 3),
            "threshold": MAX_OVERLAY_LATENCY_RATIO,
        },
    )

    assert ratio <= MAX_OVERLAY_LATENCY_RATIO
