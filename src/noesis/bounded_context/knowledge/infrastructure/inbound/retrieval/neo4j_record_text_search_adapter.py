"""Lexical search (`IRecordTextSearch`) over the `knowledge_fulltext` index."""

import re
from typing import Any, Final, LiteralString

from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.retrieval_schema_steps import (
    KNOWLEDGE_FULLTEXT_INDEX,
)
from noesis.shared_kernel.contracts.knowledge import RecordHitContract
from noesis.shared_kernel.contracts.ports.retrieval import IRecordTextSearch
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

_SPECIALS: Final[re.Pattern[str]] = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')
_OPERATORS: Final[re.Pattern[str]] = re.compile(r"\b(AND|OR|NOT)\b")

# The index holds every revision and experience. Only head revisions of knowledge in the space
# and experiences in the space survive; the procedure yields by descending score, ties break by id.
_SEARCH: LiteralString = """
CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
OPTIONAL MATCH (node)-[:REVISION_OF]->(knowledge:Knowledge {space_id: $space_id})
WITH node, score, knowledge
WHERE (knowledge IS NOT NULL AND node.number = knowledge.head_revision)
   OR (node:Experience AND node.space_id = $space_id)
RETURN CASE WHEN knowledge IS NULL THEN node.id ELSE knowledge.id END AS record_id,
       CASE WHEN knowledge IS NULL THEN null ELSE node.number END AS revision,
       score
ORDER BY score DESC, record_id
LIMIT $limit
"""


def escape_lucene(text: str) -> str:
    """`text` as plain Lucene terms: special characters escaped, operator words lowered."""
    escaped: str = _SPECIALS.sub(lambda match: "\\" + match.group(0), text)
    return _OPERATORS.sub(lambda match: match.group(0).lower(), escaped).strip()


class Neo4jRecordTextSearchAdapter(IRecordTextSearch):
    """Searches Knowledge's full-text index; hits are ranked 1..n by score."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client: Neo4jClient = client

    async def search(self, text: str, *, space_id: str, limit: int) -> list[RecordHitContract]:
        """Up to `limit` head revisions and experiences of the space matching `text`."""
        query: str = escape_lucene(text)
        if not query:
            return []
        async with await self._client.begin() as transaction:
            rows: list[dict[str, Any]] = await transaction.run(
                _SEARCH,
                {
                    "index": KNOWLEDGE_FULLTEXT_INDEX,
                    "query": query,
                    "space_id": space_id,
                    "limit": limit,
                },
            )
        return [
            RecordHitContract(record_id=row["record_id"], revision=row["revision"], rank=rank)
            for rank, row in enumerate(rows, start=1)
        ]
