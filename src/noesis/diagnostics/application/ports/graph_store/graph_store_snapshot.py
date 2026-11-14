"""What was observed about the graph store."""

from noesis.diagnostics.application.enums import GraphStoreStatusEnum
from noesis.utils import FrozenObject


class GraphStoreSnapshot(FrozenObject):
    """Facts about the graph store.

    Attributes:
        status: How far the inspection got.
        uri: The store's URI without credentials.
        message: Why it did not get further; empty when reachable.
        applied_steps: Names of the schema steps recorded as applied (empty on a new store).
    """

    status: GraphStoreStatusEnum
    uri: str
    message: str = ""
    applied_steps: frozenset[str] = frozenset()
