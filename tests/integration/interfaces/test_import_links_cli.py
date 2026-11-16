"""C3b acceptance through child processes against an isolated testcontainer."""

import shutil
from pathlib import Path

import pytest
from tests.support.import_support import (
    K1,
    K2,
    K3,
    K5,
    K6,
    K8,
    N1,
    ONE_PIXEL_PNG,
    file_snapshot,
    graph_digest,
    graph_session,
    seed_status,
)
from tests.support.noesis_process_support import run_noesis, store_environment

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

# Recounted by row: L1=4, L2=1, L3=1, L5=2 resolved occurrences; seven edges,
# four non-empty sources (the spec's tentative "created 5" is an arithmetic typo).
TOTALS = {"resolved": 8, "dangling": 1, "ambiguous": 1, "non_note": 1, "not_imported": 2, "self": 1}
EDGES = sorted(
    [
        (K1, K5, "LINKS_TO", 1, ()),
        (K1, K2, "LINKS_TO", 2, ("Steps",)),
        (K1, K8, "LINKS_TO", 1, ()),
        (K2, K1, "EMBEDS", 1, ()),
        (K3, K1, "LINKS_TO", 1, ()),
        (K5, K1, "LINKS_TO", 1, ("Why",)),
        (K5, K3, "LINKS_TO", 1, ()),
    ]
)


@pytest.fixture
def links_env(tmp_path, neo4j_settings):
    root = tmp_path / "vault"
    shutil.copytree(Path(__file__).parents[2] / "fixtures/vault_links", root)
    (root / "assets").mkdir()
    (root / "assets/diagram.png").write_bytes(ONE_PIXEL_PNG)
    env = store_environment(
        tmp_path / "child",
        "personal",
        neo4j_settings,
        NOESIS_VAULT_DIR=str(root),
        NOESIS_IMPORT_VAULT_KEY="links",
    )
    assert run_noesis(["store", "init"], env).code == 0
    return env, root


def edges(session):
    return sorted(
        (row["source"], row["target"], row["kind"], row["count"], tuple(row["anchors"]))
        for row in session.run(
            "MATCH (s:Knowledge)-[r:LINKS_TO|EMBEDS]->(t:Knowledge) WHERE r.origin = 'migrated' "
            "RETURN s.id AS source, t.id AS target, type(r) AS kind, r.count AS count, r.anchors AS anchors"
        )
    )


def invoke(env, root, *flags):
    before = file_snapshot(root)
    result = run_noesis(["import", "run", "--verbose", *flags], env)
    assert result.code == 0, result.stdout + result.stderr
    assert file_snapshot(root) == before
    return result.result


def test_preview_apply_rerun_edit_restore_and_defer(links_env, neo4j_settings):
    env, root = links_env
    with graph_session(neo4j_settings) as session:
        before = graph_digest(session)
        preview = invoke(env, root)
        assert preview["links"] == TOTALS
        assert preview["link_sets"]["planned"] == 4
        assert graph_digest(session) == before
        first = invoke(env, root, "--yes")
        assert first["links"] == TOTALS
        assert first["link_sets"] == {
            "created": 4,
            "replaced": 0,
            "unchanged": 0,
            "deferred": 0,
            "no_record": 1,
            "blocked": 0,
        }
        assert edges(session) == EDGES
        assert session.run("MATCH (n:LinkSet) RETURN count(n) AS n").single()["n"] == 4
        assert session.run("MATCH (n:Change) RETURN count(n) AS n").single()["n"] == 8
        row = next(row for row in first["notes"] if row["path"].endswith("dup-user.md"))
        assert row["ambiguous"] == [
            {"target": "dup", "candidates": ["misc/dup.md", "repos/beta/dup.md"]}
        ]
        stable = graph_digest(session)
        second = invoke(env, root, "--yes")
        assert second["link_sets"]["unchanged"] == 4
        assert graph_digest(session) == stable
        text = run_noesis(["import", "run"], env, json_output=False)
        assert "links: 8 resolved, 1 dangling, 1 ambiguous" in text.stdout
        brief = run_noesis(["import", "run"], env).result
        assert "notes" not in brief and "links" in brief and "link_sets" in brief
        original = (root / N1).read_text()
        (root / N1).write_text(original.replace("[[use-neo4j]]", "[[misc/dup]]"))
        deferred = invoke(env, root, "--yes")
        assert deferred["link_sets"]["deferred"] == 1
        assert edges(session) == EDGES
        changed = invoke(env, root, "--yes", "--update")
        assert changed["link_sets"]["replaced"] == 1
        assert (K1, K6, "LINKS_TO", 1, ()) in edges(session)
        assert (K1, K5, "LINKS_TO", 1, ()) not in edges(session)
        assert session.run("MATCH (n:Change) RETURN count(n) AS n").single()["n"] == 9
        (root / N1).write_text(original)
        restored = invoke(env, root, "--yes", "--update")
        assert restored["link_sets"]["replaced"] == 1
        assert edges(session) == EDGES
        assert (
            session.run(
                "MATCH (n:LinkSet {source_record_id: $id}) RETURN n.version AS v", id=K1
            ).single()["v"]
            == 3
        )
        assert session.run("MATCH (n:Change) RETURN count(n) AS n").single()["n"] == 10


def test_successor_owns_outgoing_edges_but_incoming_stay_accepted(links_env, neo4j_settings):
    env, root = links_env
    invoke(env, root, "--yes")
    with graph_session(neo4j_settings) as session:
        seed_status(session, K1, "accepted")
        path = root / N1
        path.write_text(path.read_text().replace("[[use-neo4j]]", "[[misc/dup]]"))
        result = invoke(env, root, "--yes", "--update")
        row = next(row for row in result["notes"] if row["path"] == N1)
        successor = row["record_id"]
        assert row["outcome"] == "successor_proposed" and successor != K1
        actual = edges(session)
        assert set(EDGES) <= set(actual)
        assert (successor, K6, "LINKS_TO", 1, ()) in actual
        assert not any(target == successor for _, target, *_ in actual)


def test_missing_schema_fails_before_any_record_write(links_env, neo4j_settings):
    env, root = links_env
    with graph_session(neo4j_settings) as session:
        session.run(
            "MATCH (m:StoreMeta) SET m.applied_steps = [s IN m.applied_steps WHERE s <> 'links']"
        ).consume()
        before = graph_digest(session)
        result = run_noesis(["import", "run", "--yes"], env)
        assert result.code == 1 and "KNOWLEDGE_204" in result.stdout and "links" in result.stdout
        assert graph_digest(session) == before
        preview = invoke(env, root)
        assert preview["link_sets"]["planned"] == 4
