"""The step of a store access during which a Neo4j failure happened."""

from enum import StrEnum


class Neo4jPhaseEnum(StrEnum):
    """Where a failure happened; reported as `phase` in error metadata.

    CONNECT: opening the connection and beginning the transaction (nothing was sent).
    QUERY: running a statement inside an open transaction (nothing was committed).
    COMMIT: committing; when the connection is lost here the outcome is unknown.
    """

    CONNECT = "connect"
    QUERY = "query"
    COMMIT = "commit"
