"""Question about the graph store that diagnostics asks."""

import abc

from .graph_store_snapshot import GraphStoreSnapshot


class IGraphStoreProbe(abc.ABC):
    """Read-only look at the configured graph store; it never writes and never raises for an outage."""

    @abc.abstractmethod
    async def inspect(self) -> GraphStoreSnapshot:
        """Connect, and report reachability and the applied schema steps."""
        ...
