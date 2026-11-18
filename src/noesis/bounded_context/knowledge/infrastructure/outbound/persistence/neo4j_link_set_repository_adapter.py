"""The sole owner of imported LINKS_TO/EMBEDS/RELATES_TO edge writes."""

from typing import Any, LiteralString

from noesis.bounded_context.knowledge.domain.entities.link_set import LinkSet
from noesis.bounded_context.knowledge.domain.repositories.i_link_set_repository import (
    ILinkSetRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.bounded_context.knowledge.domain.value_objects.enums import RecordRelationEnum
from noesis.bounded_context.knowledge.domain.value_objects.link_set_digest import LinkSetDigest
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.domain.value_objects.record_relation import RecordRelation

from .neo4j_write_support import TransactionProvider

_READ: LiteralString = "MATCH (s:LinkSet {source_record_id: $source}) RETURN properties(s) AS node"
_EDGES: LiteralString = """
MATCH (:Knowledge {id: $source})-[r:LINKS_TO|EMBEDS]->(target:Knowledge)
WHERE r.origin = $origin
RETURN target.id AS target, type(r) AS kind, r.count AS count, r.anchors AS anchors
ORDER BY target.id, type(r)
"""
_RELATIONS: LiteralString = """
MATCH (:Knowledge {id: $source})-[r:RELATES_TO]->(target:Knowledge)
WHERE r.origin = $origin
RETURN target.id AS target, r.relation AS relation
ORDER BY target.id, r.relation
"""
_LOCK: LiteralString = """
MERGE (s:LinkSet {source_record_id: $source})
SET s._lock = true
REMOVE s._lock
"""
_SAVE: LiteralString = """
MATCH (s:LinkSet {source_record_id: $source})
SET s.space_id = $space, s.origin = $origin, s.version = $version,
    s.digest = $digest, s.updated_at = $updated_at
"""
_DELETE: LiteralString = """
MATCH (:Knowledge {id: $source})-[r:LINKS_TO|EMBEDS]->(:Knowledge {id: $target})
WHERE r.origin = $origin AND type(r) = $kind
DELETE r
"""
_DELETE_RELATION: LiteralString = """
MATCH (:Knowledge {id: $source})-[r:RELATES_TO]->(:Knowledge {id: $target})
WHERE r.origin = $origin AND r.relation = $relation
DELETE r
"""
_MERGE_RELATION: LiteralString = """
MATCH (s:Knowledge {id: $source}), (t:Knowledge {id: $target})
MERGE (s)-[:RELATES_TO {origin: $origin, relation: $relation}]->(t)
"""
_MERGE_LINK: LiteralString = """
MATCH (s:Knowledge {id: $source}), (t:Knowledge {id: $target})
MERGE (s)-[r:LINKS_TO {origin: $origin}]->(t)
SET r.count = $count, r.anchors = $anchors
"""
_MERGE_EMBED: LiteralString = """
MATCH (s:Knowledge {id: $source}), (t:Knowledge {id: $target})
MERGE (s)-[r:EMBEDS {origin: $origin}]->(t)
SET r.count = $count, r.anchors = $anchors
"""


class Neo4jLinkSetRepositoryAdapter(ILinkSetRepository):
    """Serialize each source and diff edges in a single ascending target order."""

    def __init__(self, transaction: TransactionProvider) -> None:
        self._transaction: TransactionProvider = transaction

    async def lock(self, source: RecordId) -> None:
        """MERGE handles first creation; the property write also locks existing nodes."""
        await self._transaction().run(_LOCK, {"source": source.value})

    async def get(self, source: RecordId) -> LinkSet | None:
        """Read after the lock on writes, without a lock for assessments."""
        rows = await self._transaction().run(_READ, {"source": source.value})
        if not rows or "version" not in rows[0]["node"]:
            return None
        node: dict[str, Any] = rows[0]["node"]
        edges = await self._transaction().run(
            _EDGES, {"source": source.value, "origin": node["origin"]}
        )
        relations = await self._transaction().run(
            _RELATIONS, {"source": source.value, "origin": node["origin"]}
        )
        return LinkSet(
            source_record_id=source,
            space_id=SpaceId(value=node["space_id"]),
            origin=node["origin"],
            version=node["version"],
            digest=LinkSetDigest(value=node["digest"]),
            updated_at=node["updated_at"],
            links=frozenset(
                RecordLink(
                    target_record_id=RecordId(value=row["target"]),
                    link_type="embeds" if row["kind"] == "EMBEDS" else "links_to",
                    count=row["count"],
                    anchors=tuple(row["anchors"]),
                )
                for row in edges
            ),
            relations=frozenset(
                RecordRelation(
                    target_record_id=RecordId(value=row["target"]),
                    relation=RecordRelationEnum(row["relation"]),
                )
                for row in relations
            ),
        )

    async def save(self, link_set: LinkSet) -> None:
        """Diff only this origin's edges; other origins survive untouched."""
        source: str = link_set.source_record_id.value
        origin: str = link_set.origin
        old = await self._transaction().run(_EDGES, {"source": source, "origin": origin})
        wanted = {
            (
                link.target_record_id.value,
                "EMBEDS" if link.link_type == "embeds" else "LINKS_TO",
            ): link
            for link in link_set.links
        }
        keys: set[tuple[str, str]] = {(row["target"], row["kind"]) for row in old} | set(wanted)
        for target, kind in sorted(keys):
            parameters: dict[str, Any] = {
                "source": source,
                "target": target,
                "kind": kind,
                "origin": origin,
            }
            link: RecordLink | None = wanted.get((target, kind))
            if link is None:
                await self._transaction().run(_DELETE, parameters)
            else:
                parameters.update(count=link.count, anchors=list(link.anchors))
                await self._transaction().run(
                    _MERGE_EMBED if kind == "EMBEDS" else _MERGE_LINK, parameters
                )
        await self._save_relations(link_set)
        await self._transaction().run(
            _SAVE,
            {
                "source": source,
                "space": link_set.space_id.value,
                "origin": origin,
                "version": link_set.version,
                "digest": link_set.digest.value,
                "updated_at": link_set.updated_at,
            },
        )

    async def _save_relations(self, link_set: LinkSet) -> None:
        """Diff this origin's relation edges by (target, relation)."""
        parameters: dict[str, Any] = {
            "source": link_set.source_record_id.value,
            "origin": link_set.origin,
        }
        old = await self._transaction().run(_RELATIONS, parameters)
        wanted: set[tuple[str, str]] = {
            (relation.target_record_id.value, relation.relation.value)
            for relation in link_set.relations
        }
        existing: set[tuple[str, str]] = {(row["target"], row["relation"]) for row in old}
        for target, relation in sorted(existing | wanted):
            query: LiteralString = (
                _MERGE_RELATION if (target, relation) in wanted else _DELETE_RELATION
            )
            await self._transaction().run(
                query, {**parameters, "target": target, "relation": relation}
            )
