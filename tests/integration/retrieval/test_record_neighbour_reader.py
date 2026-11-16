"""Q-013: neighbours are Knowledge and Experience records that share a Source with a seed."""

import pytest
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.retrieval.retrieval_neo4j_support import (
    capture_experience,
    capture_knowledge,
    commit_source,
    space_id_of,
)

from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

SRC_A, SRC_B, SRC_C, SRC_Z = (commit_source(fill) for fill in "abcf")


async def test_neighbours_share_sources_with_seeds_and_exclude_seeds_and_unrelated_records(
    env: Neo4jKnowledgeEnv,
) -> None:
    """S1 cites A,B and S2 cites B,C (so the seeds share B); all records are in one project."""
    space_id: str = await space_id_of(env)
    seed_1 = await capture_knowledge(env, "s1", "seed one", project="acme", sources=(SRC_A, SRC_B))
    seed_2 = await capture_knowledge(env, "s2", "seed two", project="acme", sources=(SRC_B, SRC_C))
    n1 = await capture_knowledge(env, "n1", "near one", project="acme", sources=(SRC_A, SRC_B))
    n2 = await capture_knowledge(env, "n2", "near two", project="acme", sources=(SRC_A,))
    n3 = await capture_knowledge(env, "n3", "near three", project="acme", sources=(SRC_C,))
    unrelated = await capture_knowledge(
        env, "z", "same project, no shared source", project="acme", sources=(SRC_Z,)
    )
    experience = await capture_experience(env, "e", "saw it fail", sources=(SRC_A,))

    found = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [seed_1, seed_2], space_id=space_id, limit=50
    )

    found = found.neighbours
    pairs = {(item.record_id, item.seed_id): item.shared_sources for item in found}
    assert pairs == {
        (n1, seed_1): 2,
        (n1, seed_2): 1,
        (n2, seed_1): 1,
        (n3, seed_2): 1,
        (experience, seed_1): 1,
    }
    assert unrelated not in {item.record_id for item in found}
    assert {seed_1, seed_2}.isdisjoint({item.record_id for item in found})
    assert {(item.relation, item.distance) for item in found} == {("shared_source", 1)}
    assert all(item.contract_version == 1 for item in found)


async def test_limit_ranks_neighbours_by_the_sum_of_sources_shared_with_each_seed(
    env: Neo4jKnowledgeEnv,
) -> None:
    """One Source shared with two seeds (sum 2) outranks one Source shared with one seed (sum 1)."""
    space_id: str = await space_id_of(env)
    seed_1 = await capture_knowledge(env, "s1", "seed one", sources=(SRC_A, SRC_B))
    seed_2 = await capture_knowledge(env, "s2", "seed two", sources=(SRC_B,))
    single = await capture_knowledge(env, "n1", "one seed, one source", sources=(SRC_A,))
    both = await capture_knowledge(env, "n2", "two seeds, one source", sources=(SRC_B,))

    found = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [seed_1, seed_2], space_id=space_id, limit=1
    )

    found = found.neighbours
    assert {item.record_id for item in found} == {both}
    assert single not in {item.record_id for item in found}


async def test_live_links_keep_original_targets_successors_and_backlinks(
    env: Neo4jKnowledgeEnv,
) -> None:
    """C3b edges are structural, with accepted supersession followed independently."""
    space = await space_id_of(env)
    a = await capture_knowledge(env, "a", "seed", sources=(SRC_A,))
    old = await capture_knowledge(env, "old", "old", sources=(SRC_B,))
    new = await capture_knowledge(env, "new", "new", sources=(SRC_C,))
    outgoing = await capture_knowledge(env, "out", "not inherited", sources=(SRC_Z,))
    async with await env.client.begin() as tx:
        await tx.run(
            """
        MATCH (a:Record {id: $a}), (o:Record {id: $old}), (n:Record {id: $new}), (x:Record {id: $out})
        SET o.status = 'superseded', n.status = 'accepted'
        CREATE (a)-[:LINKS_TO {origin: 'vault_import', count: 9, anchors: ['section']}]->(o)
        CREATE (a)-[:EMBEDS {origin: 'vault_import', count: 2, anchors: []}]->(o)
        CREATE (o)-[:LINKS_TO {origin: 'vault_import', count: 1, anchors: []}]->(x)
        CREATE (s:Record:Assertion {id: 'supersession', space_id: $space, predicate: 'supersedes', status: 'accepted'})
        CREATE (s)-[:SUBJECT]->(n) CREATE (s)-[:OBJECT]->(o)
        """,
            {"a": a, "old": old, "new": new, "out": outgoing, "space": space},
        )
        await tx.commit()
    adapter = Neo4jRecordNeighbourReaderAdapter(env.client)
    found = await adapter.neighbours([a], space_id=space, limit=10)
    found = found.neighbours
    assert {item.record_id for item in found} == {old, new}
    assert all(item.shared_sources == 0 and item.original_target_id == old for item in found)
    assert {item.relation for item in found} == {"links_to", "embeds"}
    assert all(
        item.supersession_path == ("supersession", new) for item in found if item.record_id == new
    )
    backlinks = await adapter.neighbours([new], space_id=space, limit=10)
    backlinks = backlinks.neighbours
    assert {item.record_id for item in backlinks} == {a}
    assert all(
        item.direction == "incoming" and item.original_target_id == old for item in backlinks
    )
    assert outgoing not in {item.record_id for item in backlinks}


@pytest.mark.parametrize("mode", ["proposed", "retracted", "cycle", "depth", "overflow"])
async def test_invalid_supersession_never_guesses_a_terminal(
    env: Neo4jKnowledgeEnv, mode: str
) -> None:
    space = await space_id_of(env)
    a = await capture_knowledge(env, "a", "seed", sources=(SRC_A,))
    old = await capture_knowledge(env, "old", "old", sources=(SRC_B,))
    count = 51 if mode == "overflow" else 9 if mode == "depth" else 1
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (a:Record {id: $a}), (o:Record {id: $old})
        CREATE (a)-[:LINKS_TO {origin: 'vault_import', count: 1, anchors: []}]->(o)""",
            {"a": a, "old": old},
        )
        predecessor = old
        for index in range(count):
            target = f"successor-{index}"
            await tx.run(
                """MATCH (old:Record {id: $old})
            CREATE (new:Record:Knowledge {id: $new, space_id: $space, status: $status})
            CREATE (s:Record:Assertion {id: $assertion, space_id: $space, predicate: 'supersedes', status: $assertion_status})
            CREATE (s)-[:SUBJECT]->(new) CREATE (s)-[:OBJECT]->(old)""",
                {
                    "old": old if mode == "overflow" else predecessor,
                    "new": target,
                    "space": space,
                    "status": "retracted" if mode == "retracted" else "accepted",
                    "assertion": f"s-{index}",
                    "assertion_status": "proposed" if mode == "proposed" else "accepted",
                },
            )
            predecessor = target
        if mode == "cycle":
            await tx.run(
                """MATCH (o:Record {id: $old}), (n:Record {id: $new})
            CREATE (s:Record:Assertion {id: 'back', space_id: $space, predicate: 'supersedes', status: 'accepted'})
            CREATE (s)-[:SUBJECT]->(o) CREATE (s)-[:OBJECT]->(n)""",
                {"old": old, "new": predecessor, "space": space},
            )
        await tx.commit()
    found = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [a], space_id=space, limit=10
    )
    warnings = found.warnings
    found = found.neighbours
    assert {item.record_id for item in found} == {old}
    if mode in {"cycle", "depth", "overflow"}:
        assert warnings


async def test_combined_target_cap_prefers_multiple_seeds_over_early_ids(
    env: Neo4jKnowledgeEnv,
) -> None:
    space = await space_id_of(env)
    a = await capture_knowledge(env, "a", "seed a", sources=(SRC_A,))
    b = await capture_knowledge(env, "b", "seed b", sources=(SRC_B,))
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (a:Record {id: $a}), (b:Record {id: $b})
        CREATE (z:Record:Knowledge {id: 'z-best', space_id: $space, status: 'proposed'})
        CREATE (a)-[:LINKS_TO]->(z) CREATE (b)-[:EMBEDS]->(z)
        WITH a UNWIND range(1, 60) AS i
        CREATE (r:Record:Knowledge {id: 'a-' + toString(i), space_id: $space, status: 'proposed'})
        CREATE (a)-[:LINKS_TO {count: 1000}]->(r)
        """,
            {"a": a, "b": b, "space": space},
        )
        await tx.commit()
    batch = await Neo4jRecordNeighbourReaderAdapter(env.client).neighbours(
        [a, b], space_id=space, limit=1
    )
    assert {path.record_id for path in batch.neighbours} == {"z-best"}
    assert {path.seed_id for path in batch.neighbours} == {a, b}


async def test_diamond_preserves_both_paths_and_empty_result_keeps_cycle_diagnostic(
    env: Neo4jKnowledgeEnv,
) -> None:
    space = await space_id_of(env)
    a = await capture_knowledge(env, "a", "seed", sources=(SRC_A,))
    old = await capture_knowledge(env, "old", "old", sources=(SRC_B,))
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (a:Record {id: $a}), (old:Record {id: $old})
        CREATE (a)-[:LINKS_TO]->(old)
        CREATE (left:Record:Knowledge {id: 'left', space_id: $space, status: 'accepted'})
        CREATE (right:Record:Knowledge {id: 'right', space_id: $space, status: 'accepted'})
        CREATE (terminal:Record:Knowledge {id: 'terminal', space_id: $space, status: 'accepted'})
        WITH old, left, right, terminal
        UNWIND [[old, left, 's1'], [old, right, 's2'], [left, terminal, 's3'], [right, terminal, 's4']] AS pair
        WITH pair[0] AS o, pair[1] AS n, pair[2] AS id
        CREATE (s:Record:Assertion {id: id, space_id: $space, predicate: 'supersedes', status: 'accepted'})
        CREATE (s)-[:OBJECT]->(o) CREATE (s)-[:SUBJECT]->(n)
        """,
            {"a": a, "old": old, "space": space},
        )
        await tx.commit()
    adapter = Neo4jRecordNeighbourReaderAdapter(env.client)
    batch = await adapter.neighbours([a], space_id=space, limit=10)
    assert len([path for path in batch.neighbours if path.record_id == "terminal"]) == 2
    assert not batch.warnings
    async with await env.client.begin() as tx:
        await tx.run(
            """MATCH (old:Record {id: $old}), (terminal:Record {id: 'terminal'})
        CREATE (s:Record:Assertion {id: 'cycle', space_id: $space, predicate: 'supersedes', status: 'accepted'})
        CREATE (s)-[:OBJECT]->(terminal) CREATE (s)-[:SUBJECT]->(old)
        WITH old MATCH ()-[edge:LINKS_TO]->(old) DELETE edge
        """,
            {"old": old, "space": space},
        )
        await tx.commit()
    batch = await adapter.neighbours(["terminal"], space_id=space, limit=10)
    assert not batch.neighbours
    assert any("cycle" in warning for warning in batch.warnings)
