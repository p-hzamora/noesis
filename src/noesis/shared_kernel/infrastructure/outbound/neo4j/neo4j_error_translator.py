"""Turns Neo4j driver exceptions into noesis's typed errors.

This is the only module that names driver exception types (D-014): every other module sees
`GraphStore*Error` from `noesis.exceptions`. Messages and metadata never carry credentials.
"""

import re
from typing import Final

from neo4j.exceptions import (
    AuthError,
    ConnectionAcquisitionTimeoutError,
    ConstraintError,
    DatabaseUnavailable,
    DriverError,
    Neo4jError,
    ServiceUnavailable,
    SessionExpired,
    TransientError,
)

from noesis.exceptions import (
    AppException,
    GraphStoreAuthenticationFailedError,
    GraphStoreBusyError,
    GraphStoreConstraintViolatedError,
    GraphStoreQueryFailedError,
    GraphStoreUnavailableError,
)
from noesis.shared_kernel.domain import JsonValue

from .neo4j_connection_settings import Neo4jConnectionSettings
from .neo4j_phase_enum import Neo4jPhaseEnum

type Neo4jDriverException = Neo4jError | DriverError

DRIVER_EXCEPTIONS: Final[tuple[type[Neo4jError], type[DriverError]]] = (Neo4jError, DriverError)
"""What callers of the driver catch and hand to `translate_neo4j_error`."""

UNAVAILABLE_NEXT_STEPS: Final[tuple[str, ...]] = (
    "Check that Neo4j is running at the configured URI (NOESIS_NEO4J_URI).",
    "Run `noesis doctor`.",
    "Retry with the same idempotency key; it is safe even if the commit outcome is unknown.",
)
_CONSTRAINT_LABEL_PROPERTY: Final[re.Pattern[str]] = re.compile(
    r"label `(?P<label>[^`]+)` and property `(?P<property>[^`]+)`"
)
_REASON_LIMIT: Final[int] = 300


def _reason(error: Exception) -> str:
    """A short, single-line reason taken from the driver error."""
    message: str = getattr(error, "message", None) or str(error) or type(error).__name__
    return " ".join(message.split())[:_REASON_LIMIT]


def _status(error: Exception) -> dict[str, JsonValue]:
    """The Neo4j status code and GQL status, when the server sent them."""
    found: dict[str, JsonValue] = {}
    if isinstance(error, Neo4jError) and error.code:
        found["neo4j_code"] = error.code
    gql_status: str = getattr(error, "gql_status", "") or ""
    if gql_status:
        found["gql_status"] = gql_status
    return found


def _unavailable(
    error: Exception, *, settings: Neo4jConnectionSettings, phase: Neo4jPhaseEnum
) -> GraphStoreUnavailableError:
    metadata: dict[str, JsonValue] = {
        "uri": settings.public_uri,
        "database": settings.database,
        "connect_timeout_seconds": settings.connect_timeout_seconds,
        "phase": phase.value,
    }
    if phase is Neo4jPhaseEnum.COMMIT:
        metadata["commit_outcome"] = "unknown"
    return GraphStoreUnavailableError(
        f"Neo4j at {settings.public_uri} is unavailable during {phase.value} ({_reason(error)}).",
        metadata,
        next_steps=UNAVAILABLE_NEXT_STEPS,
    )


def translate_neo4j_error(
    error: Neo4jDriverException, *, settings: Neo4jConnectionSettings, phase: Neo4jPhaseEnum
) -> AppException:
    """Map one driver exception to the typed error a caller can branch on.

    Args:
        error: The exception the driver raised.
        settings: The connection in use, for metadata (never the password).
        phase: When it happened (connect, query or commit).

    Returns:
        `GraphStoreUnavailableError` (unreachable, connection lost, database down),
        `GraphStoreAuthenticationFailedError`, `GraphStoreBusyError` (transient),
        `GraphStoreConstraintViolatedError`, or `GraphStoreQueryFailedError` for anything else.
    """
    match error:
        case AuthError():
            return GraphStoreAuthenticationFailedError(
                f"Neo4j at {settings.public_uri} rejected the configured credentials.",
                {"uri": settings.public_uri, "user": settings.user, **_status(error)},
                next_steps=(
                    "Check NOESIS_NEO4J_USER and NOESIS_NEO4J_PASSWORD in your user-side profile.",
                ),
            )
        case ConstraintError():
            metadata: dict[str, JsonValue] = {"phase": phase.value, **_status(error)}
            if found := _CONSTRAINT_LABEL_PROPERTY.search(error.message or ""):
                metadata["label"] = found["label"]
                metadata["property"] = found["property"]
            return GraphStoreConstraintViolatedError(
                f"Neo4j rejected a write that breaks a uniqueness constraint ({_reason(error)}).",
                metadata,
            )
        case (
            ServiceUnavailable()
            | SessionExpired()
            | ConnectionAcquisitionTimeoutError()
            | DatabaseUnavailable()
        ):
            return _unavailable(error, settings=settings, phase=phase)
        case TransientError():
            return GraphStoreBusyError(
                f"Neo4j is busy and refused the work ({_reason(error)}).",
                {"phase": phase.value, **_status(error)},
                next_steps=("Retry the command; it is safe with the same idempotency key.",),
            )
        case _:
            return GraphStoreQueryFailedError(
                f"Neo4j rejected the statement ({type(error).__name__}: {_reason(error)}).",
                {"phase": phase.value, **_status(error)},
            )
