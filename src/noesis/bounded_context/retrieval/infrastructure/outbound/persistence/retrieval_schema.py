"""Retrieval's schema steps: index cursor uniqueness and the semantic chunk nodes."""

from typing import Final, LiteralString

RETRIEVAL_INDEX_STEP: Final[str] = "retrieval_index"

RETRIEVAL_INDEX_STATEMENTS: Final[tuple[LiteralString, ...]] = (
    "CREATE CONSTRAINT index_cursor_key IF NOT EXISTS "
    "FOR (n:IndexCursor) REQUIRE n.cursor_key IS UNIQUE",
)
"""`IndexCursor.cursor_key` is `<projection>:<space_id>`; the bootstrap wraps these in a step."""

RETRIEVAL_SEMANTIC_STEP: Final[str] = "retrieval_semantic"

RETRIEVAL_SEMANTIC_STATEMENTS: Final[tuple[LiteralString, ...]] = (
    "CREATE CONSTRAINT embedding_key IF NOT EXISTS "
    "FOR (n:Embedding) REQUIRE n.embedding_key IS UNIQUE",
    "CREATE INDEX embedding_record IF NOT EXISTS FOR (n:Embedding) ON (n.space_id, n.record_id)",
    "CREATE VECTOR INDEX retrieval_semantic_vector IF NOT EXISTS "
    "FOR (e:Embedding) ON (e.vector) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
)
"""C5b: unique chunk identities, the per-record lookup and the 384-dimension cosine index.

Applied after `retrieval_index` by `store init`; never by a read command. An existing index with
other options is not replaced (`IF NOT EXISTS`): the step's check reports it for repair.
"""
