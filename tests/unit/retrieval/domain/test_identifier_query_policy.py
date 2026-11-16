"""Q-205 / AC-211: the deterministic identifier-like query classifier."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.identifier_query_policy import (
    IdentifierQueryPolicy,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "why `RecordSearcher` drops stale hits",
        "what does --require-semantic do",
        "src/noesis/core/env.py",
        r"C:\Users\me",
        "os.path handling",
        "README.md wording",
        "index_lock_ttl_seconds default",
        "recordSearcher bug",
        "RecordSearcher bug",
        "550e8400-e29b-41d4-a716-446655440000",
        "NOE-123 regression",
        "K-1",
    ],
)
def test_identifier_like_queries(query: str) -> None:
    assert IdentifierQueryPolicy().is_identifier(query)


@pytest.mark.parametrize(
    "query",
    [
        "how do we keep search fast",
        "Why did the sync fail? It stopped.",
        "graph neighbours, shared sources; authority tiers!",
        "e.g. retries",
        "Neo4j vector index",
        "a - b",
    ],
)
def test_ordinary_prose_is_not_identifier_like(query: str) -> None:
    assert not IdentifierQueryPolicy().is_identifier(query)
