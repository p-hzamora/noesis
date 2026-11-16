"""Assemble `report-<arm>.json` and `.md` from the stage files of `staged.py`.

    env -u VIRTUAL_ENV PYTHONPATH=src:. uv run python -m scripts.retrieval_spike.staged_report \\
        --state DIR --out SPIKE_DIR ARM...
"""

# ruff: noqa: T201

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .arms import ARMS
from .metrics import latency_summary


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _cli(arm_dir: Path, corpus: str) -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {"cold": [], "warm": []}
    floor: list[float] = []
    for phase in rows:
        for offset in (0, 10):
            data = _load(arm_dir / f"{corpus}-cli-{phase}-{offset}.json")
            rows[phase] += data["rows"]
            floor += data["floor_help_seconds"]
    return {
        "process_floor_help": latency_summary(floor),
        "cold": latency_summary([row["seconds"] for row in rows["cold"]]),
        "warm": latency_summary([row["seconds"] for row in rows["warm"]]),
        "failures": sum(1 for phase in rows.values() for row in phase if row["exit"] != 0),
        "semantic_states": sorted(
            {
                row["index"]["semantic"]["state"]
                for phase in rows.values()
                for row in phase
                if "index" in row
            }
        ),
        "rows_cold": rows["cold"],
    }


def build(state: Path, arm_name: str) -> dict[str, Any]:
    """The arm's report dictionary."""
    arm_dir = state / arm_name
    arm = ARMS[arm_name]
    fx_rel = _load(arm_dir / "fx-relevance.json")
    sc_rel = _load(arm_dir / "sc-relevance.json")
    rel = fx_rel["relevance"]
    slices = rel["per_slice"]
    main_load = arm_dir / "fx-load-main.json"
    ids = _load(main_load if main_load.exists() else arm_dir / "fx-load.json")["ids"]
    to_key = {record_id: key for key, record_id in ids.items()}
    ranked = {row["id"]: row["ranked"] for row in rel["per_query"]}
    fx_cli = _cli(arm_dir, "fx")
    sc_cli = _cli(arm_dir, "sc")
    mismatches = 0
    compared = 0
    queries = [row for row in fx_cli["rows_cold"] if row["exit"] == 0]
    for row in queries:
        compared += 1
        if [to_key.get(i, "?") for i in row["ids"]] != ranked[row["id"]]:
            mismatches += 1
    for cli in (fx_cli, sc_cli):
        cli.pop("rows_cold")
    rebuild_fx = _load(arm_dir / "fx-rebuild.json")
    rebuild_sc = _load(arm_dir / "sc-rebuild.json")
    sc_load = _load(arm_dir / "sc-load.json")
    en, es = slices["en-en"]["ndcg@10"], slices["es-es"]["ndcg@10"]
    spot = _load(arm_dir / "fx-spot.json") if (arm_dir / "fx-spot.json").exists() else None
    stale = _load(arm_dir / "fx-stale.json")
    lag = _load(arm_dir / "fx-lag.json")
    sc_seconds = rebuild_sc["result"]["result"]["projections"][0]["duration_seconds"]
    fx_seconds = rebuild_fx["rebuild"]["result"]["projections"][0]["duration_seconds"]
    return {
        "arm": {**{k: getattr(arm.spec, k) for k in ("name", "description", "model_id", "store")}},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {
            "neo4j_image": "neo4j:5.26.33-community",
            "analyser": "standard",
            "cpu_note": "other worktrees ran Neo4j/pytest concurrently; shared 8-core machine",
        },
        "relevance": {
            "per_slice": slices,
            "overall_judged": rel["overall_judged"],
            "language_groups": rel["language_groups"],
            "no_relevant_slice": rel["no_relevant_slice"],
            "semantic_states": rel["semantic_states"],
            "in_process_latency_ms": rel["in_process_latency"],
        },
        "model_gate": {
            "es_over_en_ndcg": round(es / en, 4),
            "cross_lingual_recall@10": rel["language_groups"]["cross_lingual"]["recall@10"],
        },
        "project_filter": fx_rel["project_filter"],
        "cli_latency": {"fixture": fx_cli, "scale_2000": sc_cli},
        "cli_vs_in_process_top10": {"compared": compared, "mismatches": mismatches},
        "helper_vs_vectra_cli_spot_check": spot,
        "diluted_relevance_2000": sc_rel["relevance"],
        "index": {
            "fixture_rebuild_seconds": round(fx_seconds, 2),
            "fixture_per_record_ms": round(fx_seconds / 200 * 1000, 1),
            "scale_rebuild_seconds": round(sc_seconds, 2),
            "scale_rebuild_wall_seconds": rebuild_sc["wall_seconds"],
            "scale_per_record_ms": round(sc_seconds / 2000 * 1000, 1),
            "nfr_004_10_min_ok": sc_seconds <= 600,
            "index_commands_after_rebuild": sc_rel["index_commands"],
        },
        "lag": lag,
        "stale": stale,
        "embedding": _load(arm_dir / "fx-embed.json"),
        "disk": {
            "fixture_store": {
                "arm_store_kb": rebuild_fx["arm_store"],
                "neo4j_kb": rebuild_fx["neo4j_disk"],
            },
            "scale_neo4j_before_index_kb": sc_load.get("neo4j_disk_before_index"),
            "scale_neo4j_after_index_kb": sc_rel.get("neo4j_disk_after_index"),
            "scale_arm_store_kb": sc_rel.get("arm_store"),
        },
        "disk_post_checkpoint": _load(arm_dir / "disk-post-checkpoint.json")
        if (arm_dir / "disk-post-checkpoint.json").exists()
        else None,
        "b_runtime": {
            key: fx_rel[key]
            for key in ("embedder_ready", "query_embed_ms_in_search", "neo4j_vector_query_seconds")
            if key in fx_rel
        },
        "a_runtime": {"helper_ready": fx_rel.get("helper_ready")},
    }


def _row(name: str, m: dict[str, Any]) -> str:
    return (
        f"| {name} | {m['n']} | {m['ndcg@10']:.3f} | {m['recall@10']:.3f} "
        f"| {m['recall_core@10']:.3f} | {m['mrr@10']:.3f} |"
    )


def _lat(name: str, m: dict[str, Any]) -> str:
    return f"| {name} | {m['n']} | {m['p50_ms']} | {m['p95_ms']} | {m['max_ms']} |"


def markdown(report: dict[str, Any]) -> str:
    """The Markdown rendering of a report."""
    arm = report["arm"]
    rel = report["relevance"]
    flt = report["project_filter"]
    cli = report["cli_latency"]
    idx = report["index"]
    lag = report["lag"]
    stale = report["stale"]
    emb = report["embedding"]["service"]
    gate = report["model_gate"]
    lines = [
        f"# Spike report, arm {arm['name']}",
        "",
        f"Generated {report['generated_at']} by `scripts/retrieval_spike/staged.py` and "
        f"`staged_report.py`; Neo4j `{report['environment']['neo4j_image']}`; analyser `standard`. "
        f"Model: `{arm['model_id']}`. {arm['description']}.",
        "",
        "Relevance is the fused output of `RecordSearcher` with the arm's candidate source; for "
        "A1/A2 that source is a resident helper running Vectra's own search handler over the "
        "arm's LanceDB collection (spec 40 amendment), the CLI runs the real per-call `vectra "
        "search`. Machine shared with other worktrees; latencies carry CPU noise.",
        "",
        "## Relevance on the fixture set (fused output, all projects)",
        "",
        "| Slice | Queries | nDCG@10 | Recall@10 | Recall@10 (grade 3) | MRR@10 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_row(name, m) for name, m in rel["per_slice"].items()]
    lines.append(_row("all judged", rel["overall_judged"]))
    lines += [_row(name, m) for name, m in rel["language_groups"].items()]
    none = rel["no_relevant_slice"]
    lines += [
        "",
        f"No-relevant slice: hit counts {none['hit_counts']} (semantic returns top-k with no "
        "score floor, so a query with no relevant record still returns 10 hits).",
        "",
        "Model gate numbers: Spanish nDCG@10 / English nDCG@10 = "
        f"{gate['es_over_en_ndcg']:.3f}; pooled cross-lingual Recall@10 = "
        f"{gate['cross_lingual_recall@10']:.3f}.",
        "",
        "## Project filter",
        "",
        f"{flt['n_queries']} queries, filter keeps {flt['mean_fraction_of_records_kept']:.1%}. "
        f"Recall@10 filtered {flt['recall@10_filtered']:.3f} vs unfiltered "
        f"{flt['recall@10_unfiltered']:.3f} (ratio {flt['filtered_over_unfiltered']}); "
        f"filter shortfalls {flt['filter_shortfalls']}.",
        "",
        "## Latency (ms)",
        "",
        "| Where | n | p50 | p95 | max |",
        "| --- | --- | --- | --- | --- |",
        _lat("CLI process floor (`noesis --help`)", cli["fixture"]["process_floor_help"]),
        _lat("CLI search, fixture, cold", cli["fixture"]["cold"]),
        _lat("CLI search, fixture, warm", cli["fixture"]["warm"]),
        _lat("CLI search, 2000 records, cold", cli["scale_2000"]["cold"]),
        _lat("CLI search, 2000 records, warm", cli["scale_2000"]["warm"]),
        _lat("in-process search, resident model/helper, fixture", rel["in_process_latency_ms"]),
        "",
        "Sample: 20 queries (every third judged query), one fresh `noesis search` process per "
        "call; cold = first run of each text, warm = the same 20 commands again (one pass, so "
        "p95 is the 19th of 20). "
        f"CLI failures: {cli['fixture']['failures']} fixture, {cli['scale_2000']['failures']} scale; "
        f"semantic.state seen in CLI: {cli['fixture']['semantic_states']}. "
        f"CLI vs in-process top-10 mismatches: {report['cli_vs_in_process_top10']['mismatches']} "
        f"of {report['cli_vs_in_process_top10']['compared']}.",
    ]
    spot = report["helper_vs_vectra_cli_spot_check"]
    if spot:
        lines += [
            "",
            f"Helper vs `vectra search` CLI top-10 paths: {sum(r['equal'] for r in spot['rows'])} "
            f"of {len(spot['rows'])} queries identical (all equal: {spot['all_equal']}).",
        ]
    lines += [
        "",
        "## Index time, lag and rebuild",
        "",
        f"- Fixture rebuild (200 records): {idx['fixture_rebuild_seconds']} s "
        f"({idx['fixture_per_record_ms']} ms per record).",
        f"- Scale rebuild (2,000 records, `noesis index rebuild --yes`): "
        f"{idx['scale_rebuild_seconds']} s ({idx['scale_per_record_ms']} ms per record); "
        f"NFR-004 (10 min) met: {idx['nfr_004_10_min_ok']}.",
        f"- Indexing lag (capture commit to `index sync` exit with cursor at head, n={lag['lag_seconds']['n']}): "
        f"p50 {lag['lag_seconds']['p50_ms']} ms, p95 {lag['lag_seconds']['p95_ms']} ms; cursors at "
        f"head: {lag['all_cursors_at_head']}; no-op `index sync` floor p50 "
        f"{lag['noop_index_sync_seconds']['p50_ms']} ms. The lag includes the sync process's own "
        "start, model start-up and the store write.",
        "",
        "## Stale hits after a revise",
        "",
        f"5 records revised (searched with `--status proposed`, because tiers outrank fusion and a "
        f"revised proposed record otherwise falls below ten accepted semantic hits). Before sync: "
        f"served stale or missing {stale['stale_after_revise']['served_stale_or_missing']}; the "
        f"stale-hit counter dropped {stale['stale_after_revise']['stale_hits_counter_total']} "
        f"old-revision candidates. After `index sync`: stale served "
        f"{stale['stale_after_sync']['served_old_revision']}, counter "
        f"{stale['stale_after_sync']['stale_hits_total_after_sync']}, new text at head "
        f"{stale['stale_after_sync']['new_text_found_at_head']} of 5, new text also found by "
        f"semantic {stale['stale_after_sync']['new_text_found_by_semantic']} of 5.",
        "",
        "## Embedding and background-service evidence",
        "",
        f"- Model `{emb['model_id']}`, dimension {emb['dimension']}, window {emb['max_seq_length']} "
        f"tokens; fixture record texts: max {emb['tokens_max']} tokens, p95 {emb['tokens_p95']}, "
        f"{emb['texts_over_window']} over the window (the generated 2,000 records are the same "
        "length class).",
        "- Fresh helper start (interpreter, torch import, model load), 3 starts: "
        + ", ".join(f"{s['start_to_ready_s']} s" for s in emb["starts"])
        + f" (import {emb['starts'][0]['import_ms']} ms, load {emb['starts'][0]['load_ms']} ms).",
        f"- Resident model, one query: p50 {emb['resident_query_embed_ms']['p50_ms']} ms, p95 "
        f"{emb['resident_query_embed_ms']['p95_ms']} ms; batch of 64 documents "
        f"{emb['resident_batch_64_docs_ms']} ms ({emb['docs_per_second_batched']} docs/s).",
    ]
    if report["b_runtime"]:
        runtime = report["b_runtime"]
        lines.append(
            f"- Within the resident search: embedding p50 "
            f"{runtime['query_embed_ms_in_search']['p50_ms']} ms; Neo4j `queryNodes` p50 "
            f"{runtime['neo4j_vector_query_seconds']['p50_ms']} ms, p95 "
            f"{runtime['neo4j_vector_query_seconds']['p95_ms']} ms."
        )
    disk = {**report["disk"], "disk_post_checkpoint": report["disk_post_checkpoint"]}
    lines += [
        "",
        "## Disk and dependency weight",
        "",
        f"- Model cache: {report['embedding']['model_cache_kb'] / 1024:.0f} MB; Vectra's tool "
        f"environment (interpreter, torch, sentence-transformers, LanceDB): "
        f"{report['embedding']['vectra_env_kb'] / 1024:.0f} MB.",
        f"- Fixture store: {disk['fixture_store']}.",
        f"- Scale (2,000 records): Neo4j before index {disk['scale_neo4j_before_index_kb']}, after "
        f"{disk['scale_neo4j_after_index_kb']} (kB; Community has no `db.checkpoint`, so sizes "
        f"may lag unflushed writes); arm store {disk['scale_arm_store_kb']}.",
        "",
        *(
            [
                "- Neo4j after a checkpoint (container restarted; 2,000 records with the vector "
                f"index): database {disk['disk_post_checkpoint']['database_kb']} kB, schema "
                f"indexes {disk['disk_post_checkpoint']['schema_index_kb']} kB of which the vector "
                f"index {disk['disk_post_checkpoint']['vector_index_dir_kb']} kB (about 8 MB "
                "database before the index, unflushed).",
            ]
            if disk["disk_post_checkpoint"]
            else []
        ),
        "",
        "## Diluted relevance at scale (fixture judgments over 2,000 records)",
        "",
        "| Slice | Queries | nDCG@10 | Recall@10 | Recall@10 (grade 3) | MRR@10 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_row(n, m) for n, m in report["diluted_relevance_2000"]["per_slice"].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write the reports of the arms named on the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("arms", nargs="+")
    args = parser.parse_args()
    for name in args.arms:
        report = build(args.state, name)
        (args.out / f"report-{name}.json").write_text(json.dumps(report, indent=1))
        (args.out / f"report-{name}.md").write_text(markdown(report))
        print(f"wrote report-{name}")


if __name__ == "__main__":
    main()
