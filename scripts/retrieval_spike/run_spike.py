"""Measurement harness for the C5a vector placement spike (`specs/40-vector-spike.md`).

Not a test: it lives outside `tests/` and is never collected by pytest or imported by `src/`.
It starts ONLY a testcontainers Neo4j (never the user's database, vault or Vectra store) and gives
every child process a temporary HOME. Run it from the repository root:

    env -u VIRTUAL_ENV PYTHONPATH=src:. uv run python -m scripts.retrieval_spike.run_spike --arm A2

Arms: L (default), A1, A2, B. A1/A2/B add a projection through `launcher.py` (D-025); they need
the cached models (`HF_HOME`) and Vectra's tool environment, and download nothing.
"""

# ruff: noqa: T201, S101

import argparse
import asyncio
import json
import os
import platform
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.neo4j_container import pinned_neo4j_image, running_neo4j
from tests.support.noesis_process_support import run_noesis, store_environment
from tests.support.retrieval.retrieval_neo4j_support import (
    build_searcher,
    revise_knowledge,
    search_request,
    space_id_of,
)

from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

from . import semantic_measure as sm
from .arms import ARMS
from .corpus import LoadResult, generate_records, load_records, open_env
from .fixtures import (
    SLICES,
    FixtureQuery,
    FixtureRecord,
    load_queries,
)
from .fixtures import (
    load_records as load_fixture,
)
from .metrics import CUTOFF, latency_summary, mean, mrr_at_k, ndcg_at_k, recall_at_k

DEFAULT_OUT = Path(
    "/home/phzamora/Desktop/noesis/.claude/planning/c5-retrieval-vector-decision/spike"
)
SPACE = "default"


def _queries() -> list[FixtureQuery]:
    """All queries; `SPIKE_SMOKE=1` keeps every seventh (wiring checks only, never a report)."""
    queries = load_queries()
    return queries[::7] if os.environ.get("SPIKE_SMOKE") else queries


def _cli_args(query: FixtureQuery | str, *extra: str) -> list[str]:
    text = query if isinstance(query, str) else query.text
    return ["search", text, "--all-projects", "--limit", str(CUTOFF), *extra]


def _hit_keys(ids: Sequence[str], to_key: dict[str, str]) -> list[str]:
    return [to_key.get(record_id, f"?{record_id}") for record_id in ids]


STALE_LIMIT = 10
STALE_STATUSES = ("proposed",)  # tiers outrank fusion: a proposed hit sits below accepted ones


async def _timed_search(
    searcher: RecordSearcher,
    space_id: str,
    text: str,
    *,
    project: str | None = None,
    limit: int = CUTOFF,
    statuses: tuple[str, ...] = (),
) -> tuple[Any, float]:
    request = search_request(
        text,
        space_id,
        project_key=project,
        all_projects=project is None,
        limit=limit,
        statuses=statuses,
    )
    started = time.perf_counter()
    result = await searcher.search(request)
    return result, time.perf_counter() - started


def _slice_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "ndcg@10": round(mean([row["ndcg"] for row in rows]), 4),
        "recall@10": round(mean([row["recall"] for row in rows]), 4),
        "recall_core@10": round(mean([row["recall_core"] for row in rows]), 4),
        "mrr@10": round(mean([row["mrr"] for row in rows]), 4),
    }


async def evaluate_relevance(
    searcher: RecordSearcher,
    space_id: str,
    queries: Sequence[FixtureQuery],
    to_key: dict[str, str],
    *,
    passes: int = 3,
) -> dict[str, Any]:
    """Fused-output metrics per slice (all projects), plus in-process latency over `passes`."""
    per_query: list[dict[str, Any]] = []
    latencies: list[float] = []
    for pass_number in range(passes):
        for query in queries:
            result, seconds = await _timed_search(searcher, space_id, query.text)
            latencies.append(seconds)
            if pass_number:
                continue
            ranked = _hit_keys([hit.record_id for hit in result.hits], to_key)
            per_query.append(
                {
                    "id": query.id,
                    "slice": query.slice,
                    "hits": len(ranked),
                    "ranked": ranked,
                    "ndcg": ndcg_at_k(ranked, query.relevance),
                    "recall": recall_at_k(ranked, query.relevance),
                    "recall_core": recall_at_k(ranked, query.relevance, min_grade=3),
                    "mrr": mrr_at_k(ranked, query.relevance),
                    "sources": sorted({kind.value for hit in result.hits for kind in hit.sources}),
                    "stale_hits": result.stale_hits,
                    "semantic_state": result.semantic_state.value,
                }
            )
    judged = [row for row in per_query if row["slice"] != "none"]
    by_slice = {name: [row for row in judged if row["slice"] == name] for name in SLICES[:-1]}
    none_rows = [row for row in per_query if row["slice"] == "none"]
    return {
        "per_slice": {name: _slice_metrics(rows) for name, rows in by_slice.items()},
        "overall_judged": _slice_metrics(judged),
        "language_groups": {
            "english_query": _slice_metrics(by_slice["en-en"] + by_slice["en-es"]),
            "spanish_query": _slice_metrics(by_slice["es-es"] + by_slice["es-en"]),
            "cross_lingual": _slice_metrics(by_slice["es-en"] + by_slice["en-es"]),
        },
        "no_relevant_slice": {
            "n": len(none_rows),
            "fraction_zero_hits": round(
                mean([1.0 if row["hits"] == 0 else 0.0 for row in none_rows]), 3
            ),
            "hit_counts": [row["hits"] for row in none_rows],
            "note": "arm L has no score in the fused output, so only hit counts are reported",
        },
        "stale_hits_total": sum(row["stale_hits"] for row in per_query),
        "semantic_states": sorted({row["semantic_state"] for row in per_query}),
        "in_process_latency": latency_summary(latencies),
        "per_query": per_query,
    }


async def evaluate_filter(
    searcher: RecordSearcher,
    space_id: str,
    queries: Sequence[FixtureQuery],
    records: Sequence[FixtureRecord],
    to_key: dict[str, str],
) -> dict[str, Any]:
    """Recall@10 with `--project` (project plus space-wide records) against all projects.

    Only judgments inside the filter's scope count, so both sides share one denominator.
    """
    project_of = {record.key: record.project for record in records}
    rows: list[dict[str, Any]] = []
    for query in queries:
        if query.project is None:
            continue
        scoped = {
            key: grade
            for key, grade in query.relevance.items()
            if project_of[key] in (query.project, None)
        }
        if not any(grade >= 1 for grade in scoped.values()):
            continue
        filtered, _ = await _timed_search(searcher, space_id, query.text, project=query.project)
        unfiltered, _ = await _timed_search(searcher, space_id, query.text)
        filtered_keys = _hit_keys([hit.record_id for hit in filtered.hits], to_key)
        unfiltered_keys = _hit_keys([hit.record_id for hit in unfiltered.hits], to_key)
        rows.append(
            {
                "id": query.id,
                "recall_filtered": recall_at_k(filtered_keys, scoped),
                "recall_unfiltered": recall_at_k(unfiltered_keys, scoped),
                "ndcg_filtered": ndcg_at_k(filtered_keys, scoped),
                "ndcg_unfiltered": ndcg_at_k(unfiltered_keys, scoped),
                "shortfall": filtered.filter_shortfall,
            }
        )
    kept = Counter(record.project for record in records)
    kept_sizes = [kept[query.project] + kept[None] for query in queries if query.project]
    filtered_recall = mean([row["recall_filtered"] for row in rows])
    unfiltered_recall = mean([row["recall_unfiltered"] for row in rows])
    return {
        "n_queries": len(rows),
        "mean_fraction_of_records_kept": round(mean(kept_sizes) / len(records), 4),
        "recall@10_filtered": round(filtered_recall, 4),
        "recall@10_unfiltered": round(unfiltered_recall, 4),
        "filtered_over_unfiltered": round(filtered_recall / unfiltered_recall, 4)
        if unfiltered_recall
        else None,
        "ndcg@10_filtered": round(mean([row["ndcg_filtered"] for row in rows]), 4),
        "ndcg@10_unfiltered": round(mean([row["ndcg_unfiltered"] for row in rows]), 4),
        "filter_shortfalls": sum(1 for row in rows if row["shortfall"]),
    }


def cli_latency(
    settings: Neo4jConnectionSettings,
    queries: Sequence[FixtureQuery],
    to_key: dict[str, str],
    *,
    warm_passes: int = 2,
    check_against: dict[str, list[str]] | None = None,
    ctx: sm.ArmContext | None = None,
) -> dict[str, Any]:
    """Wall-clock of `python -m noesis search ... --json`, one fresh process per call.

    Cold: pass 1 over `queries`, straight after the container was loaded; each text is run for
    the first time and the first call also pays Neo4j's first-query costs. Warm: the following
    `warm_passes` passes of the same commands. Every call is a new process, so interpreter and
    import time is inside both figures; `process_floor` is `noesis --help`.
    """
    runner = ctx.run if ctx else run_noesis
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = (
            ctx.cli_env(Path(home_name), settings)
            if ctx
            else store_environment(Path(home_name), SPACE, settings)
        )
        floor = [runner(["--help"], env, json_output=False).seconds for _ in range(5)]
        passes: list[list[float]] = []
        mismatches = failures = 0
        for pass_number in range(1 + warm_passes):
            seconds: list[float] = []
            for query in queries:
                outcome = runner(_cli_args(query), env)
                seconds.append(outcome.seconds)
                if outcome.code != 0:
                    failures += 1
                    continue
                if pass_number == 0 and check_against is not None:
                    hits = outcome.result["hits"]
                    assert isinstance(hits, list)
                    ids = [hit["id"] for hit in hits]
                    if _hit_keys(ids, to_key) != check_against[query.id]:
                        mismatches += 1
            passes.append(seconds)
    warm = [value for pass_seconds in passes[1:] for value in pass_seconds]
    return {
        "calls_per_pass": len(queries),
        "process_floor_help": latency_summary(floor),
        "cold_pass1": latency_summary(passes[0]),
        "warm_pass2plus": latency_summary(warm),
        "failures": failures,
        "cli_vs_in_process_top10_mismatches": mismatches if check_against is not None else None,
        "definition": "cold = pass 1 (first run of each text, fresh processes, just-loaded container); "
        "warm = later passes of identical commands; new process per call, so no model or client is "
        "cached between calls",
    }


def index_commands(settings: Neo4jConnectionSettings) -> dict[str, Any]:
    """`index sync|status|rebuild` with no projection registered (arm L): evidence of N/A."""
    out: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        env = store_environment(Path(home_name), SPACE, settings)
        for name, args in (
            ("sync", ["index", "sync"]),
            ("status", ["index", "status"]),
            ("rebuild", ["index", "rebuild", "--yes"]),
        ):
            outcome = run_noesis(args, env)
            body = outcome.envelope.get("result") if outcome.code == 0 else outcome.envelope
            out[name] = {"exit": outcome.code, "seconds": round(outcome.seconds, 2), "result": body}
    return out


async def stale_after_revise(
    env: Neo4jKnowledgeEnv,
    searcher: RecordSearcher,
    settings: Neo4jConnectionSettings,
    space_id: str,
    load: LoadResult,
    records_by_key: dict[str, FixtureRecord],
    keys: Sequence[str],
    ctx: sm.ArmContext | None = None,
) -> dict[str, Any]:
    """Revise still-proposed records, then search the new and the old text.

    A hit is stale when served at a revision that is not the head. The new text must find the
    record at revision 2 in the same process and in a fresh CLI process (AC-006); the old title
    must not return the record at revision 1.
    """
    rows: list[dict[str, Any]] = []
    runner = ctx.run if ctx else run_noesis
    with tempfile.TemporaryDirectory(prefix="spike-home-") as home_name:
        cli_env = (
            ctx.cli_env(Path(home_name), settings)
            if ctx
            else store_environment(Path(home_name), SPACE, settings)
        )
        for number, key in enumerate(keys, start=1):
            record_id = load.ids[key]
            marker = f"quokkafresh{number}"
            await revise_knowledge(
                env,
                record_id,
                f"spike-revise-{key}",
                expected=1,
                title=f"{marker} replacement heading",
                body=f"{marker} replacement note about gardening and compost",
            )
            fresh, _ = await _timed_search(
                searcher, space_id, marker, limit=STALE_LIMIT, statuses=STALE_STATUSES
            )
            fresh_revisions = {hit.record_id: hit.revision for hit in fresh.hits}
            cli_fresh = runner([*_cli_args(marker), "--status", "proposed"], cli_env).result["hits"]
            assert isinstance(cli_fresh, list)
            cli_revisions = {hit["id"]: hit["revision"] for hit in cli_fresh}
            old, _ = await _timed_search(
                searcher,
                space_id,
                records_by_key[key].title or "",
                limit=STALE_LIMIT,
                statuses=STALE_STATUSES,
            )
            old_revisions = {hit.record_id: hit.revision for hit in old.hits}
            rows.append(
                {
                    "key": key,
                    "found_new_text_in_process_at_revision": fresh_revisions.get(record_id),
                    "found_new_text_via_fresh_cli_at_revision": cli_revisions.get(record_id),
                    "old_title_returned_record_at_revision": old_revisions.get(record_id),
                    "stale_hits_counter": fresh.stale_hits + old.stale_hits,
                }
            )
    served_stale = sum(
        1
        for row in rows
        if row["old_title_returned_record_at_revision"] not in (None, 2)
        or row["found_new_text_in_process_at_revision"] not in (2,)
        or row["found_new_text_via_fresh_cli_at_revision"] not in (2,)
    )
    return {
        "revised": len(rows),
        "served_stale_or_missing": served_stale,
        "stale_hits_counter_total": sum(row["stale_hits_counter"] for row in rows),
        "rows": rows,
    }


def _corpus_summary(
    records: Sequence[FixtureRecord], queries: Sequence[FixtureQuery]
) -> dict[str, Any]:
    return {
        "records": len(records),
        "by_language": dict(Counter(record.lang for record in records)),
        "by_type": dict(Counter(record.kind for record in records)),
        "knowledge_target_status": dict(
            Counter(record.status for record in records if record.kind == "knowledge")
        ),
        "projects": len({record.project for record in records if record.project}),
        "space_wide_records": sum(1 for record in records if record.project is None),
        "queries": len(queries),
        "queries_by_slice": dict(Counter(query.slice for query in queries)),
    }


def _load_summary(load: LoadResult) -> dict[str, Any]:
    count = len(load.capture_seconds)
    total_capture = sum(load.capture_seconds)
    return {
        "records_captured": count,
        "capture_total_s": round(total_capture, 2),
        "capture_throughput_per_s": round(count / total_capture, 2) if total_capture else None,
        "capture_latency": latency_summary(load.capture_seconds),
        "status_writes": len(load.status_seconds),
        "status_write_total_s": round(sum(load.status_seconds), 2),
        "wall_total_s": round(load.total_seconds, 2),
    }


STALE_KEYS = ("E01.3", "E02.3", "E05.3", "S01.3", "S02.3")


async def run_fixture(
    settings: Neo4jConnectionSettings, passes: int, ctx: sm.ArmContext | None = None
) -> dict[str, Any]:
    """Fixture corpus: relevance, filter, CLI latency, index commands and stale hits."""
    records = load_fixture()
    queries = _queries()
    env = await open_env(settings)
    registered = None
    try:
        space_id = await space_id_of(env)
        load = await load_records(env, space_id, records)
        to_key = {record_id: key for key, record_id in load.ids.items()}
        extra: dict[str, Any] = {}
        if ctx is None:
            searcher = build_searcher(env)
        else:
            os.environ.update(ctx.env_extra())
            sm.point_hf_cache()
            extra["rebuild"] = sm.index_rebuild(ctx, settings)
            registered = ctx.arm.registered(env.client, None)  # type: ignore[arg-type]
            searcher = sm.build_arm_searcher(env, registered)
            extra["cli_search_sample"] = sm.cli_search_sample(ctx, settings, queries[0].text)
        print(f"[{time.strftime('%X')}] step: relevance", flush=True)
        relevance = await evaluate_relevance(searcher, space_id, queries, to_key, passes=passes)
        print(f"[{time.strftime('%X')}] step: filter_result", flush=True)
        filter_result = await evaluate_filter(searcher, space_id, queries, records, to_key)
        check = {row["id"]: row["ranked"] for row in relevance["per_query"]}
        print(f"[{time.strftime('%X')}] step: cli", flush=True)
        cli = cli_latency(settings, queries, to_key, check_against=check, ctx=ctx)
        by_key = {r.key: r for r in records}
        if ctx is None:
            index: dict[str, Any] = index_commands(settings)
        else:
            index = sm.index_commands(ctx, settings)
        print(f"[{time.strftime('%X')}] step: stale", flush=True)
        stale = await stale_after_revise(
            env, searcher, settings, space_id, load, by_key, STALE_KEYS, ctx
        )
        if ctx is not None and registered is not None:
            extra["stale_after_sync"] = await sm.stale_after_sync(
                registered,
                searcher,
                ctx,
                settings,
                space_id,
                list(STALE_KEYS),
                load.ids,
                {key: by_key[key].title or "" for key in STALE_KEYS},
            )
            extra["lag"] = await sm.measure_lag(env, ctx, settings, registered, space_id, 10)
            extra["embedding_service"] = await sm.embedding_service(
                str(ctx.arm.spec.model_id),
                sm.record_texts(records),
                [query for query in queries if query.slice != "none"],
            )
        statuses = Counter(hit_status for hit_status in await _stored_statuses(settings))
        return {
            "corpus": _corpus_summary(records, queries),
            "load": _load_summary(load),
            "stored_statuses": dict(statuses),
            "relevance": relevance,
            "project_filter": filter_result,
            "cli_latency": cli,
            "index_commands": index,
            "stale_after_revise": stale,
            "semantic": extra,
        }
    finally:
        await _close_arm(ctx)
        await env.client.close()


async def _close_arm(ctx: sm.ArmContext | None) -> None:
    kit = getattr(ctx.arm, "kit", None) if ctx else None
    if kit is not None:
        await kit.embedder.close()


async def _stored_statuses(settings: Neo4jConnectionSettings) -> list[str]:
    from tests.support.knowledge_neo4j_support import query as raw_query

    rows = raw_query(settings, "MATCH (k:Knowledge) RETURN k.status AS status")
    return [row["status"] for row in rows]


async def run_scale(
    settings: Neo4jConnectionSettings,
    count: int,
    cli_queries: int,
    ctx: sm.ArmContext | None = None,
) -> dict[str, Any]:
    """Scale corpus: the fixture records plus generated ones, `count` in total, via C2's handlers."""
    fixtures = load_fixture()
    queries = _queries()
    generated = generate_records(count - len(fixtures))
    records = [*fixtures, *generated]
    env = await open_env(settings)
    try:
        space_id = await space_id_of(env)
        load = await load_records(env, space_id, records, status_share=0.5)
        to_key = {record_id: key for key, record_id in load.ids.items()}
        extra: dict[str, Any] = {}
        if ctx is None:
            searcher = build_searcher(env)
        else:
            os.environ.update(ctx.env_extra())
            sm.point_hf_cache()
            await sm.checkpoint(env)
            extra["neo4j_disk_before_index"] = sm.neo4j_disk_kb(settings)
            extra["rebuild"] = sm.index_rebuild(ctx, settings)
            await sm.checkpoint(env)
            extra["neo4j_disk_after_index"] = sm.neo4j_disk_kb(settings)
            extra["arm_store"] = sm.arm_store_kb(ctx)
            extra["index_commands"] = sm.index_commands(ctx, settings)
            registered = ctx.arm.registered(env.client, None)  # type: ignore[arg-type]
            searcher = sm.build_arm_searcher(env, registered)
        relevance = await evaluate_relevance(
            searcher, space_id, queries, to_key, passes=1 if ctx else 3
        )
        relevance.pop("per_query")
        subset = [query for query in queries if query.slice != "none"][:cli_queries]
        cli = cli_latency(settings, subset, to_key, warm_passes=2, ctx=ctx)
        return {
            "corpus": {
                "records": len(records),
                "fixture_records": len(fixtures),
                "generated_records": len(generated),
                "note": "relevance below is diluted: generated records are unjudged noise",
            },
            "load": _load_summary(load),
            "relevance_diluted": relevance,
            "cli_latency": cli,
            "semantic": extra,
        }
    finally:
        await _close_arm(ctx)
        await env.client.close()


def _row(name: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {name} | {metrics['n']} | {metrics['ndcg@10']:.3f} | {metrics['recall@10']:.3f} "
        f"| {metrics['recall_core@10']:.3f} | {metrics['mrr@10']:.3f} |"
    )


def render_markdown(report: dict[str, Any]) -> str:
    """The Markdown report: metrics tables only (the manual appendix is added by hand)."""
    fixture, scale = report["fixture"], report["scale"]
    rel = fixture["relevance"]
    lines = [
        f"# Spike report, arm {report['arm']['name']}",
        "",
        f"Generated {report['generated_at']} by `scripts/retrieval_spike/run_spike.py`; "
        f"Neo4j image `{report['environment']['neo4j_image']}`; analyser `standard`.",
        "",
        "## Relevance on the fixture set (fused output, all projects)",
        "",
        "| Slice | Queries | nDCG@10 | Recall@10 | Recall@10 (grade 3) | MRR@10 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_row(name, metrics) for name, metrics in rel["per_slice"].items()]
    lines.append(_row("all judged", rel["overall_judged"]))
    lines += [_row(name, metrics) for name, metrics in rel["language_groups"].items()]
    none = rel["no_relevant_slice"]
    flt = fixture["project_filter"]
    cold, warm, floor = (
        fixture["cli_latency"][k] for k in ("cold_pass1", "warm_pass2plus", "process_floor_help")
    )
    scold, swarm = scale["cli_latency"]["cold_pass1"], scale["cli_latency"]["warm_pass2plus"]
    lines += [
        "",
        f"No-relevant slice: fraction with zero hits {none['fraction_zero_hits']}, "
        f"hit counts {none['hit_counts']} ({none['note']}).",
        "",
        "## Project filter",
        "",
        f"{flt['n_queries']} queries, filter keeps {flt['mean_fraction_of_records_kept']:.1%} of records "
        f"(project plus space-wide). Recall@10 filtered {flt['recall@10_filtered']:.3f} vs unfiltered "
        f"{flt['recall@10_unfiltered']:.3f} (ratio {flt['filtered_over_unfiltered']}); shortfalls "
        f"{flt['filter_shortfalls']}.",
        "",
        "## Latency (ms)",
        "",
        "| Where | n | p50 | p95 | max |",
        "| --- | --- | --- | --- | --- |",
        f"| CLI process floor (`noesis --help`) | {floor['n']} | {floor['p50_ms']} | {floor['p95_ms']} | {floor['max_ms']} |",
        f"| CLI search, fixture, cold | {cold['n']} | {cold['p50_ms']} | {cold['p95_ms']} | {cold['max_ms']} |",
        f"| CLI search, fixture, warm | {warm['n']} | {warm['p50_ms']} | {warm['p95_ms']} | {warm['max_ms']} |",
        f"| in-process search, fixture | {rel['in_process_latency']['n']} | {rel['in_process_latency']['p50_ms']} | {rel['in_process_latency']['p95_ms']} | {rel['in_process_latency']['max_ms']} |",
        f"| CLI search, {scale['corpus']['records']} records, cold | {scold['n']} | {scold['p50_ms']} | {scold['p95_ms']} | {scold['max_ms']} |",
        f"| CLI search, {scale['corpus']['records']} records, warm | {swarm['n']} | {swarm['p50_ms']} | {swarm['p95_ms']} | {swarm['max_ms']} |",
        f"| in-process search, {scale['corpus']['records']} records | {scale['relevance_diluted']['in_process_latency']['n']} | {scale['relevance_diluted']['in_process_latency']['p50_ms']} | {scale['relevance_diluted']['in_process_latency']['p95_ms']} | {scale['relevance_diluted']['in_process_latency']['max_ms']} |",
        "",
        f"{fixture['cli_latency']['definition']}.",
        f"CLI failures: {fixture['cli_latency']['failures']} (fixture), "
        f"CLI vs in-process top-10 mismatches: {fixture['cli_latency']['cli_vs_in_process_top10_mismatches']}.",
        "",
        "## Capture and scale",
        "",
        f"Fixture load: {fixture['load']['records_captured']} records, "
        f"{fixture['load']['capture_throughput_per_s']} captures/s. "
        f"Scale: {scale['load']['records_captured']} records in {scale['load']['capture_total_s']} s "
        f"({scale['load']['capture_throughput_per_s']} captures/s, p95 "
        f"{scale['load']['capture_latency']['p95_ms']} ms per capture).",
        "",
        "Diluted relevance at scale (fixture judgments over the scale corpus):",
        "",
        "| Slice | Queries | nDCG@10 | Recall@10 | Recall@10 (grade 3) | MRR@10 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_row(name, m) for name, m in scale["relevance_diluted"]["per_slice"].items()]
    stale = fixture["stale_after_revise"]
    lines += [
        "",
        "## Stale hits after a revise",
        "",
        f"{stale['revised']} records revised; served stale or missing: {stale['served_stale_or_missing']}; "
        f"`stale_hits` counter total: {stale['stale_hits_counter_total']}.",
        "",
    ]
    if report["arm"]["name"] == "L":
        lines += [
            "## Index time, indexing lag and rebuild",
            "",
            "Not applicable to arm L: it registers no projection, so there is no index time per "
            "record, no indexing lag and no rebuild. `index sync`, `index status` and `index "
            "rebuild --yes` return `projections: []` with exit "
            f"{[fixture['index_commands'][k]['exit'] for k in ('sync', 'status', 'rebuild')]}. "
            "Lexical text is searchable as soon as the capture commits (the full-text index is "
            "Knowledge's).",
            "",
            "## Arms not run here",
            "",
            "A1, A2 and B are reported in their own files.",
            "",
        ]
    else:
        lines += render_semantic(report)
    return "\n".join(lines)


def model_gate(report: dict[str, Any]) -> dict[str, Any]:
    """The model-gate numbers: Spanish over English nDCG@10 and pooled cross-lingual Recall@10."""
    rel = report["fixture"]["relevance"]
    english = rel["per_slice"]["en-en"]["ndcg@10"]
    spanish = rel["per_slice"]["es-es"]["ndcg@10"]
    return {
        "es_ndcg": spanish,
        "en_ndcg": english,
        "es_over_en_ndcg": round(spanish / english, 4) if english else None,
        "cross_lingual_recall@10": rel["language_groups"]["cross_lingual"]["recall@10"],
        "cross_lingual_ndcg@10": rel["language_groups"]["cross_lingual"]["ndcg@10"],
        "fused_overall_ndcg@10": rel["overall_judged"]["ndcg@10"],
    }


def render_semantic(report: dict[str, Any]) -> list[str]:
    """Markdown for the projection-specific measurements of A1, A2 and B."""
    fixture, scale = report["fixture"], report["scale"]
    sem, ssem = fixture["semantic"], scale["semantic"]
    gate = report["gates"]
    rebuild, srebuild = sem["rebuild"], ssem["rebuild"]
    rb = rebuild["result"]["projections"][0]
    srb = srebuild["result"]["projections"][0]
    lag, svc = sem["lag"], sem["embedding_service"]
    after = sem["stale_after_sync"]
    stale = fixture["stale_after_revise"]
    lines = [
        "## Model gate numbers (fused output)",
        "",
        f"Spanish nDCG@10 {gate['es_ndcg']:.3f} / English nDCG@10 {gate['en_ndcg']:.3f} = "
        f"{gate['es_over_en_ndcg']}; cross-lingual Recall@10 (es-en and en-es pooled) "
        f"{gate['cross_lingual_recall@10']:.3f}; overall judged nDCG@10 {gate['fused_overall_ndcg@10']:.3f}.",
        "",
        "## Index time and rebuild",
        "",
        f"- Fixture (200 records) `index rebuild --yes`: {rb['records_indexed']} records, handler "
        f"duration {rb['duration_seconds']:.1f} s, CLI wall {rebuild['wall_seconds']} s "
        f"({rb['duration_seconds'] / max(rb['records_indexed'], 1) * 1000:.0f} ms per record).",
        f"- Scale ({scale['corpus']['records']} records) `index rebuild --yes`: {srb['records_indexed']} "
        f"records, handler duration {srb['duration_seconds']:.1f} s, CLI wall "
        f"{srebuild['wall_seconds']} s ({srb['duration_seconds'] / max(srb['records_indexed'], 1) * 1000:.0f} "
        "ms per record); NFR-004 limit 600 s.",
        "",
        "## Indexing lag",
        "",
        f"{len(lag['samples'])} captures, each followed by `index sync` in a fresh process: lag p50 "
        f"{lag['lag_seconds']['p50_ms']} ms, p95 {lag['lag_seconds']['p95_ms']} ms, max "
        f"{lag['lag_seconds']['max_ms']} ms; a no-op `index sync` takes p50 "
        f"{lag['noop_index_sync_seconds']['p50_ms']} ms. All cursors at head: "
        f"{lag['all_cursors_at_head']}; new record found by the semantic source right after the "
        f"sync: {sum(1 for r in lag['samples'] if r['found_by_semantic_source_after_sync'])}"
        f"/{len(lag['samples'])}. {lag['definition']}.",
        "",
        "## Stale hits after a revise",
        "",
        f"5 records revised. Before any sync (semantic index one revision behind): served stale or "
        f"missing {stale['served_stale_or_missing']}, `stale_hits` counter total "
        f"{stale['stale_hits_counter_total']} (stale semantic entries dropped by step 3). After "
        f"`index sync`: old revision served {after['served_old_revision']}, `stale_hits` total "
        f"{after['stale_hits_total_after_sync']}, new text found at head {after['new_text_found_at_head']}/5, "
        f"of which by the semantic source {after['new_text_found_by_semantic']}/5.",
        "",
        "## Semantic state observed",
        "",
        f"In-process fixture search: {fixture['relevance']['semantic_states']}. One CLI search: "
        f"`{sem['cli_search_sample']['index']}`, sources seen {sem['cli_search_sample']['sources_seen']}.",
        f"`index sync` after rebuild: exit {fixture['index_commands']['sync']['exit']}; "
        f"`index status --verify` exit {fixture['index_commands']['status_verify']['exit']}, "
        f"divergences {fixture['index_commands']['status_verify']['result'].get('divergences')}.",
        "",
        "## Embedding service evidence",
        "",
        f"Model `{svc['model_id']}`, dimension {svc['dimension']}, window {svc['max_seq_length']} tokens; "
        f"record texts {svc['record_texts']}: max {svc['tokens_max']} tokens, p95 {svc['tokens_p95']}, "
        f"over the window: {svc['texts_over_window']} (one chunk per record, the rest is truncated by "
        "the model).",
        "",
        "| Start (fresh process) | to ready (s) | torch/sentence-transformers import (ms) | model load (ms) |",
        "| --- | --- | --- | --- |",
        *(
            f"| {number} | {item['start_to_ready_s']} | {item['import_ms']} | {item['load_ms']} |"
            for number, item in enumerate(svc["starts"], start=1)
        ),
        "",
        f"Resident model: one query embedded in p50 {svc['resident_query_embed_ms']['p50_ms']} ms, p95 "
        f"{svc['resident_query_embed_ms']['p95_ms']} ms (n={svc['resident_query_embed_ms']['n']}); a batch "
        f"of 64 records {svc['resident_batch_64_docs_ms']} ms ({svc['docs_per_second_batched']} docs/s). "
        "Start 1 is the first start of this arm's run; starts 2 and 3 hit the page cache (the cache could "
        "not be dropped without root).",
        "",
        "## Weight added",
        "",
        f"- Model on disk (Hugging Face cache): {sm.model_cache_kb(str(report['arm']['model_id'])) / 1024:.0f} MB.",
        f"- Vectra's tool environment (interpreter, torch, sentence-transformers, LanceDB; not in "
        f"Noesis's environment): {sm.vectra_env_kb() / 1024:.0f} MB.",
        f"- Arm store after the scale rebuild: {ssem['arm_store']}.",
        f"- Neo4j container before / after the scale index (KB): {ssem['neo4j_disk_before_index']} / "
        f"{ssem['neo4j_disk_after_index']}.",
        "",
    ]
    return lines


async def main_async(args: argparse.Namespace) -> None:
    """Run the chosen arm and write the reports."""
    arm = ARMS[args.arm]
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "arm": {
            "name": arm.spec.name,
            "description": arm.spec.description,
            "model_id": arm.spec.model_id,
            "store": arm.spec.store,
        },
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {
            "neo4j_image": pinned_neo4j_image(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    with tempfile.TemporaryDirectory(
        prefix=f"spike-{arm.spec.name}-", dir=args.workdir_root
    ) as base:
        for phase in ("fixture", "scale"):
            ctx = None
            if args.arm != "L":
                workdir = Path(base) / phase
                workdir.mkdir()
                ctx = sm.ArmContext(arm=arm, workdir=workdir)
            with running_neo4j() as settings:
                print(f"{phase} run ...", flush=True)
                if phase == "fixture":
                    report[phase] = await run_fixture(settings, args.passes, ctx)
                else:
                    report[phase] = await run_scale(
                        settings, args.scale_records, args.scale_cli_queries, ctx
                    )
    if args.arm != "L":
        report["gates"] = model_gate(report)
    (out / f"report-{arm.spec.name}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / f"report-{arm.spec.name}.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote reports to {out}")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="L", choices=sorted(ARMS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--passes", type=int, default=3, help="in-process passes over the queries")
    parser.add_argument("--scale-records", type=int, default=2000)
    parser.add_argument("--scale-cli-queries", type=int, default=40)
    parser.add_argument("--workdir-root", type=Path, default=None, help="where arm work dirs go")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
