"""The two schema steps of catalog discovery: revision fields and the catalog full-text index."""

from typing import Final

from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CATALOG_DISCOVERY_STEP,
    CATALOG_FULLTEXT_STEP,
)

from .neo4j_store_schema_adapter import Neo4jSchemaStep

CATALOG_FULLTEXT_INDEX: Final[str] = "catalog_fulltext"

CATALOG_DISCOVERY_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=CATALOG_DISCOVERY_STEP,
    statements=(),
    backfill=(
        "MATCH (revision:Revision)-[:REVISION_OF]->(entry:CatalogEntry) "
        "WHERE NOT revision:CatalogRevision "
        "SET revision:CatalogRevision, revision.name = entry.name, "
        "revision.capabilities = coalesce(revision.capabilities, []), "
        "revision.capabilities_text = coalesce(revision.capabilities_text, ''), "
        "revision.origin = coalesce(revision.origin, 'registered')",
    ),
)
"""Labels existing catalog revisions `CatalogRevision` and gives them the new fields' defaults."""

CATALOG_FULLTEXT_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=CATALOG_FULLTEXT_STEP,
    statements=(
        "CREATE FULLTEXT INDEX catalog_fulltext IF NOT EXISTS "
        "FOR (n:CatalogRevision) ON EACH [n.name, n.purpose, n.capabilities_text] "
        "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard'}}",
    ),
)
"""Full-text index `catalog_fulltext` with the `standard` analyser."""
