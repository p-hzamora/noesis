"""C5a's two schema steps owned by Knowledge: the change feed and the full-text index.

The `retrieval_index` step (the cursor constraint) belongs to Retrieval and is registered by
the composition root. Knowledge's full-text index spans the text of head and older revisions
(`:Revision`) and of experiences (`:Experience`); the text search keeps only head revisions.
"""

from typing import Final

from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CHANGE_FEED_STEP,
    KNOWLEDGE_FULLTEXT_STEP,
)

from .neo4j_store_schema_adapter import Neo4jSchemaStep

CHANGE_FEED_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=CHANGE_FEED_STEP,
    statements=(
        "CREATE CONSTRAINT change_key IF NOT EXISTS FOR (n:Change) REQUIRE n.change_key IS UNIQUE",
        "CREATE CONSTRAINT change_counter_space IF NOT EXISTS "
        "FOR (n:ChangeCounter) REQUIRE n.space_id IS UNIQUE",
    ),
)
"""Uniqueness of `Change.change_key` (`<space_id>:<sequence>`) and `ChangeCounter.space_id`."""

KNOWLEDGE_FULLTEXT_INDEX: Final[str] = "knowledge_fulltext"

KNOWLEDGE_FULLTEXT_SCHEMA_STEP: Final[Neo4jSchemaStep] = Neo4jSchemaStep(
    name=KNOWLEDGE_FULLTEXT_STEP,
    statements=(
        "CREATE FULLTEXT INDEX knowledge_fulltext IF NOT EXISTS "
        "FOR (n:Revision|Experience) ON EACH [n.title, n.body] "
        "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard'}}",
    ),
)
"""Full-text index `knowledge_fulltext` with the `standard` analyser."""
