"""Fresh CLI sessions read only graph bodies; digest needs no model or semantic index."""

import json
import platform
from pathlib import Path

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.noesis_process_support import run_noesis
from tests.support.retrieval.retrieval_neo4j_support import capture_experience, capture_knowledge
from tests.support.retrieval.retrieval_process_support import (
    closed_store_environment,
    run_noesis_in,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


async def test_fresh_digest_scope_labels_citations_readonly_and_warm_latency(
    env: Neo4jKnowledgeEnv, child_env: dict[str, str], tmp_path: Path
):
    global_id = await capture_knowledge(env, "global", "python ports global", body="Use ports")
    project_id = await capture_knowledge(
        env, "project", "python ports project", body="Use Typer", project="demo"
    )
    proposed = await capture_knowledge(
        env, "proposal", "python ports proposal", body="Consider a plugin"
    )
    old = await capture_knowledge(env, "old", "python ports old", body="Use argparse")
    retracted = await capture_knowledge(env, "retracted", "python ports dead")
    foreign = await capture_knowledge(env, "foreign", "python ports other", project="other")
    experience = await capture_experience(env, "experience", "python ports test passed")
    async with await env.client.begin() as tx:
        await tx.run(
            "MATCH (r:Record) WHERE r.id IN $ids SET r.status = 'accepted'",
            {"ids": [global_id, project_id]},
        )
        await tx.run(
            "MATCH (r:Record {id: $id}) SET r.tags = ['origin:migrated']", {"id": proposed}
        )
        await tx.run("MATCH (r:Record {id: $id}) SET r.status = 'superseded'", {"id": old})
        await tx.run("MATCH (r:Record {id: $id}) SET r.status = 'retracted'", {"id": retracted})
        await tx.commit()
    args = ["recall", "python ports", "--project", "demo", "--no-synthesis"]
    result = run_noesis(
        args, {**child_env, "NOESIS_RETRIEVAL_BRIEFING_CLAUDE_BIN": "/missing/model"}
    )
    assert result.code == 0, (result.stdout, result.stderr)
    answer = result.result
    records = answer["records"]
    assert {record["id"] for record in records} == {
        global_id,
        project_id,
        proposed,
        old,
        experience,
    }
    assert {foreign, retracted}.isdisjoint(record["id"] for record in records)
    assert answer["synthesis"] == "digest" and answer["index"]["semantic"]["state"] == "absent"
    assert answer["next_steps"]
    read = {(record["id"], record["revision"]) for record in records if record["read"]}
    for section in ("constraints", "decisions", "context", "unconfirmed"):
        for item in answer[section]:
            assert all(
                (citation["record_id"], citation["revision"]) in read
                for citation in item["citations"]
            )
    samples = [run_noesis(args, child_env) for _ in range(20)]
    assert all(sample.code == 0 for sample in samples)
    p95 = sorted(sample.seconds for sample in samples)[18]
    measurement = {
        "samples": 20,
        "p95_seconds": p95,
        "target_seconds": 3,
        "machine": platform.machine(),
        "processor": platform.processor(),
        "runtime_probes": "none: no endorsements",
        "python": platform.python_version(),
    }
    print("C8_LATENCY=" + json.dumps(measurement))  # noqa: T201
    (tmp_path / "latency.json").write_text(json.dumps(measurement))
    assert p95 <= 3, measurement


@pytest.mark.parametrize(
    "args,code",
    [
        (["recall", "--help"], 0),
        (["recall", " "], 2),
        (["recall", "task", "--runtime", "invalid"], 2),
        (["recall", "task", "--limit", "0"], 2),
        (["recall", "task", "--unknown"], 2),
    ],
)
def test_usage_never_contacts_store(tmp_path: Path, args: list[str], code: int):
    result = run_noesis_in(
        tmp_path, args, closed_store_environment(tmp_path / "home"), json_output=False
    )
    assert result.code == code
    assert "INTEGRATION_103" not in result.stdout + result.stderr
