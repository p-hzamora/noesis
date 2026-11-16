"""Live Source/link discovery with bounded accepted-supersession traversal."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import LiteralString

from noesis.shared_kernel.contracts.knowledge import GraphNeighbourContract, GraphNeighboursContract
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jTransaction

# Rank the UNION before the one distinct-target query cap. Repeated occurrences never
# contribute to rank. Every path of a retained target is returned for provenance.
_NEIGHBOURS: LiteralString = """
CALL () {
    MATCH (seed:Record {space_id: $space_id})
    WHERE (seed:Knowledge OR seed:Experience) AND seed.id IN $seed_ids
    OPTIONAL MATCH (head:Revision {revision_key: seed.id + ':' + toString(seed.head_revision)})
    WITH seed, coalesce(head, seed) AS seed_holder
    MATCH (seed_holder)-[:FROM_SOURCE]->(source:Source {space_id: $space_id})
    MATCH (holder)-[:FROM_SOURCE]->(source)
    WHERE holder <> seed_holder
    OPTIONAL MATCH (holder)-[:REVISION_OF]->(knowledge:Knowledge {space_id: $space_id})
    WITH seed, source, holder, knowledge
    WHERE (knowledge IS NOT NULL AND holder.number = knowledge.head_revision)
       OR (holder:Experience AND holder.space_id = $space_id)
    WITH seed, source, CASE WHEN knowledge IS NULL THEN holder ELSE knowledge END AS neighbour
    WHERE NOT neighbour.id IN $seed_ids AND coalesce(neighbour.status, '') <> 'retracted'
    WITH neighbour, seed, count(DISTINCT source) AS shared
    RETURN neighbour.id AS target, {seed_id: seed.id, shared_sources: shared, relation: 'shared_source'} AS path
    UNION ALL
    UNWIND $origins AS origin
    MATCH (seed:Record {id: origin.id, space_id: $space_id})-[edge:LINKS_TO|EMBEDS]-(other:Record {space_id: $space_id})
    WHERE (other:Knowledge OR other:Experience) AND NOT other.id IN $seed_ids
      AND (NOT origin.incoming_only OR endNode(edge) = seed)
      AND coalesce(other.status, '') <> 'retracted'
    RETURN other.id AS target, {seed_id: origin.seed, shared_sources: 0, relation: toLower(type(edge)),
      direction: CASE WHEN startNode(edge) = seed THEN 'outgoing' ELSE 'incoming' END,
      original_target_id: endNode(edge).id, origin: edge.origin, anchors: coalesce(edge.anchors, []),
      occurrence_count: coalesce(edge.count, 0), supersession_path: origin.path} AS path
}
WITH target, collect(DISTINCT path) AS paths
WITH target, paths, reduce(total = 0, path IN paths | total + path.shared_sources) AS shared,
     size(reduce(seeds = [], path IN paths | CASE WHEN path.seed_id IN seeds THEN seeds ELSE seeds + path.seed_id END)) AS seed_count,
     reduce(best = 999, path IN paths | reduce(rank = best, i IN range(0, size($seed_ids)-1) | CASE WHEN $seed_ids[i] = path.seed_id AND i < rank THEN i ELSE rank END)) AS best_seed
ORDER BY CASE WHEN shared > 0 THEN 0 ELSE 1 END, shared DESC, CASE WHEN shared = 0 THEN seed_count ELSE 0 END DESC, best_seed, target
LIMIT $limit
UNWIND paths AS path
RETURN target, path
"""
_SUCCESSORS: LiteralString = """
MATCH (old:Knowledge {id: $id, space_id: $space_id})<-[:OBJECT]-(a:Assertion {space_id: $space_id, predicate: 'supersedes', status: 'accepted'})-[:SUBJECT]->(new:Knowledge {space_id: $space_id})
RETURN new.id AS id, new.status AS status, a.id AS assertion_id
ORDER BY id, assertion_id LIMIT 51
"""
_PREDECESSORS: LiteralString = """
MATCH (new:Knowledge {id: $id, space_id: $space_id})<-[:SUBJECT]-(a:Assertion {space_id: $space_id, predicate: 'supersedes', status: 'accepted'})-[:OBJECT]->(old:Knowledge {space_id: $space_id})
RETURN old.id AS id, old.status AS status, a.id AS assertion_id
ORDER BY id, assertion_id LIMIT 51
"""
_STATUS: LiteralString = """
MATCH (record:Knowledge {id: $id, space_id: $space_id})
RETURN record.status AS status
"""


@dataclass(slots=True)
class _TraversalBudget:
    """One visited-record budget for all expansions originating at one search seed."""

    visited: set[str] = field(default_factory=set)
    steps: int = 0

    def visit(self, record_id: str) -> bool:
        if record_id not in self.visited and len(self.visited) >= 50:
            return False
        self.visited.add(record_id)
        return True


class Neo4jRecordNeighbourReaderAdapter:
    """Same-space structural paths; absence of imported edges is an empty contribution."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def neighbours(
        self, seed_ids: Sequence[str], *, space_id: str, limit: int
    ) -> GraphNeighboursContract:
        """Merge Source and link targets before ranking/capping; never inherit outgoing links."""
        if not seed_ids:
            return GraphNeighboursContract()
        budgets = {seed: _TraversalBudget(visited={seed}) for seed in seed_ids}
        warnings: list[str] = []
        origins: list[JsonValue] = []
        async with await self._client.begin() as transaction:
            for seed in seed_ids:
                origins.append({"id": seed, "seed": seed, "incoming_only": False, "path": []})
                predecessors, issues = await _walk(
                    transaction, seed, space_id, backwards=True, budget=budgets[seed]
                )
                warnings.extend(f"{seed}: {issue}" for issue in issues)
                for predecessor, path in predecessors:
                    origins.append(
                        {"id": predecessor, "seed": seed, "incoming_only": True, "path": [*path]}
                    )
            rows = await transaction.run(
                _NEIGHBOURS,
                {
                    "space_id": space_id,
                    "seed_ids": [*seed_ids],
                    "origins": origins,
                    "limit": 50 * len(seed_ids) + 1,
                },
            )
            target_ids = list(dict.fromkeys(row["target"] for row in rows))
            if len(target_ids) > 50 * len(seed_ids):
                warnings.append("combined graph candidate budget exceeded; discovery is incomplete")
                retained_targets = set(target_ids[: 50 * len(seed_ids)])
                rows = [row for row in rows if row["target"] in retained_targets]
            found = [
                GraphNeighbourContract.model_validate({"record_id": row["target"], **row["path"]})
                for row in rows
            ]
            successors: dict[tuple[str, str], list[tuple[str, list[str]]]] = {}
            for base in tuple(found):
                if base.direction != "outgoing":
                    continue
                key = (base.seed_id, base.record_id)
                if key not in successors:
                    paths, issues = await _walk(
                        transaction,
                        base.record_id,
                        space_id,
                        backwards=False,
                        budget=budgets[base.seed_id],
                    )
                    successors[key] = paths
                    warnings.extend(f"{base.seed_id}: {issue}" for issue in issues)
                found.extend(
                    base.model_copy(
                        update={"record_id": successor, "supersession_path": tuple(path)}
                    )
                    for successor, path in successors[key]
                    if successor not in seed_ids
                )
        targets = {pair.record_id for pair in found}

        def rank(target: str) -> tuple[int, int, int, str]:
            pairs = [pair for pair in found if pair.record_id == target]
            shared = sum(pair.shared_sources for pair in pairs)
            seeds = {pair.seed_id for pair in pairs}
            return (
                0 if shared else 1,
                -shared if shared else -len(seeds),
                min(seed_ids.index(seed) for seed in seeds),
                target,
            )

        retained = set(sorted(targets, key=rank)[:limit])
        return GraphNeighboursContract(
            neighbours=tuple(dict.fromkeys(pair for pair in found if pair.record_id in retained)),
            warnings=tuple(dict.fromkeys(warnings)),
        )


async def _walk(
    transaction: Neo4jTransaction,
    start: str,
    space: str,
    *,
    backwards: bool,
    budget: _TraversalBudget,
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Track path-local cycles separately from shared visit accounting (diamonds are valid)."""
    if not budget.visit(start):
        return [], ["supersession visited-record limit exceeded"]
    queue: list[tuple[str, list[str], tuple[str, ...]]] = [(start, [], (start,))]
    found: list[tuple[str, list[str]]] = []
    while queue:
        current, path, ancestors = queue.pop(0)
        budget.steps += 1
        # Also bound path proliferation in a highly connected DAG, independently of ids.
        if budget.steps > 400:
            return [], ["supersession path limit exceeded"]
        rows = await transaction.run(
            _PREDECESSORS if backwards else _SUCCESSORS, {"id": current, "space_id": space}
        )
        if rows and len(ancestors) > 8:
            return [], ["supersession depth exhausted"]
        if not rows and path and not backwards:
            statuses = await transaction.run(_STATUS, {"id": current, "space_id": space})
            if statuses and statuses[0]["status"] == "accepted":
                found.append((current, path))
        for row in rows:
            target = row["id"]
            if target in ancestors:
                return [], ["supersession cycle"]
            if not budget.visit(target):
                return [], ["supersession visited-record limit exceeded"]
            if row["status"] == "retracted":
                continue
            next_path = [*path, row["assertion_id"], target]
            if backwards:
                found.append((target, next_path))
            queue.append((target, next_path, (*ancestors, target)))
    return found, []
