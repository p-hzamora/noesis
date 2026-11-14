"""How far a look at the graph store got."""

from enum import StrEnum


class GraphStoreStatusEnum(StrEnum):
    """Outcome of inspecting the graph store.

    REACHABLE: connected, authenticated and the applied schema steps were read.
    UNREACHABLE: the store could not be reached.
    AUTHENTICATION_FAILED: the store answered and rejected the credentials.
    ERROR: reached, but the inspection query failed.
    """

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    AUTHENTICATION_FAILED = "authentication_failed"
    ERROR = "error"
