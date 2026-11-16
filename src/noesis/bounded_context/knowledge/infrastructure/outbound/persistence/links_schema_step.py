"""C3b's per-source link-set uniqueness constraint."""

from typing import Final

from noesis.bounded_context.knowledge.application.services.schema_steps import LINKS_STEP

from .neo4j_store_schema_adapter import Neo4jSchemaStep

LINKS_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=LINKS_STEP,
    statements=(
        "CREATE CONSTRAINT link_set_source IF NOT EXISTS FOR (n:LinkSet) REQUIRE n.source_record_id IS UNIQUE",
    ),
)
