"""C9's schema step: one consolidation per id, one membership per record per consolidation."""

from typing import Final

from noesis.bounded_context.knowledge.application.services.schema_steps import CONSOLIDATION_STEP

from .neo4j_store_schema_adapter import Neo4jSchemaStep

CONSOLIDATION_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=CONSOLIDATION_STEP,
    statements=(
        "CREATE CONSTRAINT consolidation_id IF NOT EXISTS "
        "FOR (n:Consolidation) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT consolidation_membership_key IF NOT EXISTS "
        "FOR (n:ConsolidationMembership) REQUIRE n.membership_key IS UNIQUE",
        "CREATE CONSTRAINT consolidation_membership_open IF NOT EXISTS "
        "FOR (n:ConsolidationMembership) REQUIRE n.open_key IS UNIQUE",
    ),
)
"""`open_key` is a record id while the consolidation holds the record and is removed on dismissal."""
