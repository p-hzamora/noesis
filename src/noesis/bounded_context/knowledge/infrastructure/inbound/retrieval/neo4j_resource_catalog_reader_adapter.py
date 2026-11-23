"""Answers Retrieval's resource search: catalog full-text hits plus the live overlay.

The catalog side reads head revisions of the space through the `catalog_fulltext` index. The
overlay (`include_unsynced`) adds what the requested runtimes have installed and the catalog
does not know, scored in memory against the same terms. Nothing is written and nothing is
executed; the probes never raise.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, LiteralString

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
)
from noesis.bounded_context.knowledge.application.policies.catalog.overlay_match import (
    score_artifact,
    search_words,
)
from noesis.bounded_context.knowledge.application.ports.runtime import IRuntimeInventoryProbe
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.catalog_discovery import (
    DISCOVERABLE_KINDS,
    NO_DESCRIPTION,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CATALOG_FULLTEXT_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.catalog_discovery_schema_steps import (
    CATALOG_FULLTEXT_INDEX,
)
from noesis.shared_kernel.contracts.knowledge import (
    CatalogResourceHitContract,
    CatalogResourceLookupContract,
    CatalogResourceQueryContract,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from .neo4j_record_text_search_adapter import escape_lucene

# Only head revisions of entries of the space survive; the procedure yields by descending score.
_SEARCH: Final[LiteralString] = """
CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
MATCH (node)-[:REVISION_OF]->(entry:CatalogEntry {space_id: $space_id})
WHERE node.number = entry.head_revision
  AND (size($kinds) = 0 OR entry.entry_kind IN $kinds)
RETURN entry.id AS entry_id, entry.entry_kind AS kind, entry.name AS name,
       properties(node) AS revision, score
ORDER BY score DESC, name
LIMIT $limit
"""
_LOOKUP: Final[LiteralString] = """
MATCH (entry:CatalogEntry {space_id: $space_id})
WHERE entry.id IN $entry_ids OR (entry.entry_kind + ':' + entry.name) IN $refs
MATCH (node)-[:REVISION_OF]->(entry)
WHERE node.number = entry.head_revision
RETURN entry.id AS entry_id, entry.entry_kind AS kind, entry.name AS name,
       properties(node) AS revision, 1.0 AS score
ORDER BY name
"""
_KEYS: Final[LiteralString] = """
MATCH (entry:CatalogEntry {space_id: $space_id})
RETURN entry.entry_kind AS kind, entry.name AS name
"""

type _Key = tuple[str, str]


class Neo4jResourceCatalogReaderAdapter:
    """Retrieval's door to the catalog's resources.

    Args:
        client: The graph client (the caller closes it).
        schema: Tells which schema steps are applied.
        runtime_probes: Read-only probes by runtime; asked only when the query wants them.
    """

    def __init__(
        self,
        client: Neo4jClient,
        schema: IStoreSchema,
        runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe],
    ) -> None:
        self._client: Neo4jClient = client
        self._schema: IStoreSchema = schema
        self._runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe] = runtime_probes

    async def search(self, query: CatalogResourceQueryContract) -> list[CatalogResourceHitContract]:
        """Up to `query.limit` hits of the space, best score first, ties by name.

        Raises:
            StoreNotInitialisedError: The `catalog_fulltext` schema step is not applied.
            GraphStoreUnavailableError: The store is down; nothing was probed.
        """
        await require_steps(self._schema, CATALOG_FULLTEXT_STEP)
        words: tuple[str, ...] = search_words(*(query.terms or (query.text,)))
        rows: list[dict[str, Any]] = await self._catalog_rows(query)
        installed: dict[_Key, list[tuple[RuntimeEnum, InstalledArtifactDto]]] = {}
        if query.runtimes and query.include_unsynced:
            installed = await self._installed(query.runtimes)
        hits: list[CatalogResourceHitContract] = _catalog_hits(rows, installed)
        if query.include_unsynced and words:
            cataloged: set[_Key] = await self._catalog_keys(query.space_id)
            hits += _overlay_hits(installed, cataloged, words, query)
        hits.sort(key=lambda hit: (-hit.score, hit.name, hit.kind))
        return hits[: query.limit]

    async def get_by_refs(
        self, lookup: CatalogResourceLookupContract
    ) -> list[CatalogResourceHitContract]:
        """The entries named by `refs` or `entry_ids`, then installed artifacts for the other refs.

        Exact lookups only: a ref nothing answers is absent from the result, never invented.

        Raises:
            StoreNotInitialisedError: The `catalog_fulltext` schema step is not applied.
            GraphStoreUnavailableError: The store is down; nothing was probed.
        """
        await require_steps(self._schema, CATALOG_FULLTEXT_STEP)
        if not lookup.refs and not lookup.entry_ids:
            return []
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _LOOKUP,
                {
                    "space_id": lookup.space_id,
                    "entry_ids": list(lookup.entry_ids),
                    "refs": list(lookup.refs),
                },
            )
        installed: dict[_Key, list[tuple[RuntimeEnum, InstalledArtifactDto]]] = {}
        if lookup.runtimes and (lookup.include_unsynced or rows):
            installed = await self._installed(lookup.runtimes)
        hits: list[CatalogResourceHitContract] = _catalog_hits(rows, installed)
        if lookup.include_unsynced and lookup.runtimes:
            found: set[_Key] = {(hit.kind, hit.name) for hit in hits}
            wanted: set[_Key] = {
                (kind, name) for kind, _, name in (ref.partition(":") for ref in lookup.refs)
            }
            cataloged: set[_Key] = await self._catalog_keys(lookup.space_id)
            for key in sorted(wanted - found - cataloged):
                observations = installed.get(key)
                if not observations:
                    continue
                artifact: InstalledArtifactDto = observations[0][1]
                hits.append(
                    CatalogResourceHitContract.model_validate(
                        {
                            "kind": key[0],
                            "name": key[1],
                            "purpose": artifact.description or NO_DESCRIPTION,
                            "prerequisites": artifact.declared_requires,
                            "manifest_digest": artifact.manifest_digest,
                            "origin": "discovered",
                            "cataloged": False,
                            "discovered_runtimes": _runtimes(installed, key),
                            "score": 1.0,
                        }
                    )
                )
        return hits

    async def _catalog_rows(self, query: CatalogResourceQueryContract) -> list[dict[str, Any]]:
        lucene: str = " ".join(
            part
            for part in (escape_lucene(term) for term in (query.terms or (query.text,)))
            if part
        )
        if not lucene:
            return []
        async with await self._client.begin() as transaction:
            return await transaction.run(
                _SEARCH,
                {
                    "index": CATALOG_FULLTEXT_INDEX,
                    "query": lucene,
                    "space_id": query.space_id,
                    "kinds": list(query.kinds),
                    "limit": query.limit,
                },
            )

    async def _catalog_keys(self, space_id: str) -> set[_Key]:
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(_KEYS, {"space_id": space_id})
        return {(row["kind"], row["name"]) for row in rows}

    async def _installed(
        self, runtimes: Sequence[str]
    ) -> dict[_Key, list[tuple[RuntimeEnum, InstalledArtifactDto]]]:
        found: dict[_Key, list[tuple[RuntimeEnum, InstalledArtifactDto]]] = {}
        for value in dict.fromkeys(runtimes):
            runtime: RuntimeEnum = RuntimeEnum(value)
            probe: IRuntimeInventoryProbe | None = self._runtime_probes.get(runtime)
            if probe is None:
                continue
            inventory: RuntimeInventoryDto = await probe.inventory()
            for artifact in inventory.artifacts:
                if artifact.kind in DISCOVERABLE_KINDS:
                    found.setdefault((artifact.kind.value, artifact.name), []).append(
                        (runtime, artifact)
                    )
        return found


def _runtimes(
    installed: Mapping[_Key, Sequence[tuple[RuntimeEnum, InstalledArtifactDto]]], key: _Key
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(runtime.value for runtime, _ in installed.get(key, ())))


def _catalog_hits(
    rows: Sequence[dict[str, Any]],
    installed: Mapping[_Key, Sequence[tuple[RuntimeEnum, InstalledArtifactDto]]],
) -> list[CatalogResourceHitContract]:
    top: float = max((row["score"] for row in rows), default=0.0)
    hits: list[CatalogResourceHitContract] = []
    for row in rows:
        revision: dict[str, Any] = row["revision"]
        hits.append(
            CatalogResourceHitContract.model_validate(
                {
                    "catalog_id": row["entry_id"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "revision": revision["number"],
                    "purpose": revision["purpose"],
                    "capabilities": revision.get("capabilities") or (),
                    "prerequisites": revision["prerequisites"],
                    "manifest_digest": revision.get("manifest_digest"),
                    "origin": revision.get("origin") or "registered",
                    "cataloged": True,
                    "discovered_runtimes": _runtimes(installed, (row["kind"], row["name"])),
                    "score": row["score"] / top if top > 0 else 0.0,
                }
            )
        )
    return hits


def _overlay_hits(
    installed: Mapping[_Key, Sequence[tuple[RuntimeEnum, InstalledArtifactDto]]],
    cataloged: set[_Key],
    words: Sequence[str],
    query: CatalogResourceQueryContract,
) -> list[CatalogResourceHitContract]:
    hits: list[CatalogResourceHitContract] = []
    for key, observations in installed.items():
        if key in cataloged or (query.kinds and key[0] not in query.kinds):
            continue
        artifact: InstalledArtifactDto = observations[0][1]
        score: float = score_artifact(artifact.name, artifact.description, words)
        if score <= 0.0:
            continue
        hits.append(
            CatalogResourceHitContract.model_validate(
                {
                    "kind": key[0],
                    "name": key[1],
                    "purpose": artifact.description or NO_DESCRIPTION,
                    "prerequisites": artifact.declared_requires,
                    "manifest_digest": artifact.manifest_digest,
                    "origin": "discovered",
                    "cataloged": False,
                    "discovered_runtimes": _runtimes(installed, key),
                    "score": score,
                }
            )
        )
    return hits
