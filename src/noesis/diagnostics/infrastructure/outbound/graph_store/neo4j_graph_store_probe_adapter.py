"""`IGraphStoreProbe` over the shared Neo4j client."""

from typing import Any, Final, LiteralString

from noesis.diagnostics.application.enums import GraphStoreStatusEnum
from noesis.diagnostics.application.ports.graph_store import GraphStoreSnapshot, IGraphStoreProbe
from noesis.exceptions import (
    GraphStoreAuthenticationFailedError,
    GraphStoreBusyError,
    GraphStoreQueryFailedError,
    GraphStoreUnavailableError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

# The node the Knowledge schema adapter records applied steps on. Diagnostics may not import a
# bounded context, so the read is restated here; `tests/integration/interfaces/
# test_record_cli_neo4j.py` guards it against drift by running `store init` and then `doctor`.
STORE_META_NAME: Final[str] = "noesis"
_APPLIED: LiteralString = """
OPTIONAL MATCH (meta:StoreMeta {name: $name})
RETURN coalesce(meta.applied_steps, []) AS steps
"""


class Neo4jGraphStoreProbeAdapter(IGraphStoreProbe):
    """Opens its own client, reads the applied schema steps in one transaction, closes it."""

    def __init__(self, settings: Neo4jConnectionSettings) -> None:
        self._settings: Neo4jConnectionSettings = settings

    async def inspect(self) -> GraphStoreSnapshot:
        """Reachability, authentication and the applied schema steps; never raises for those."""
        uri: str = self._settings.public_uri
        try:
            async with Neo4jClient(self._settings) as client, await client.begin() as transaction:
                rows: list[dict[str, Any]] = await transaction.run(
                    _APPLIED, {"name": STORE_META_NAME}
                )
        except GraphStoreUnavailableError as error:
            return GraphStoreSnapshot(
                status=GraphStoreStatusEnum.UNREACHABLE, uri=uri, message=error.message
            )
        except GraphStoreAuthenticationFailedError as error:
            return GraphStoreSnapshot(
                status=GraphStoreStatusEnum.AUTHENTICATION_FAILED, uri=uri, message=error.message
            )
        except (GraphStoreBusyError, GraphStoreQueryFailedError) as error:
            return GraphStoreSnapshot(
                status=GraphStoreStatusEnum.ERROR, uri=uri, message=error.message
            )
        return GraphStoreSnapshot(
            status=GraphStoreStatusEnum.REACHABLE,
            uri=uri,
            applied_steps=frozenset(rows[0]["steps"]),
        )
