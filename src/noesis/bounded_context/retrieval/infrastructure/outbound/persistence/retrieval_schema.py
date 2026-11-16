"""Retrieval's schema step: uniqueness of the index cursor nodes."""

from typing import Final, LiteralString

RETRIEVAL_INDEX_STEP: Final[str] = "retrieval_index"

RETRIEVAL_INDEX_STATEMENTS: Final[tuple[LiteralString, ...]] = (
    "CREATE CONSTRAINT index_cursor_key IF NOT EXISTS "
    "FOR (n:IndexCursor) REQUIRE n.cursor_key IS UNIQUE",
)
"""`IndexCursor.cursor_key` is `<projection>:<space_id>`; the bootstrap wraps these in a step."""
