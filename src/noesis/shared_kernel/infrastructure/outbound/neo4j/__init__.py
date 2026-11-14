"""Shared Neo4j client: any context's persistence adapters build on it (A-2)."""

from .neo4j_client import Neo4jClient
from .neo4j_connection_settings import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_DATABASE,
    Neo4jConnectionSettings,
)
from .neo4j_phase_enum import Neo4jPhaseEnum
from .neo4j_transaction import Neo4jTransaction

__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_DATABASE",
    "Neo4jClient",
    "Neo4jConnectionSettings",
    "Neo4jPhaseEnum",
    "Neo4jTransaction",
]
