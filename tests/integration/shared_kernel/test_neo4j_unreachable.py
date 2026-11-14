"""A stopped Neo4j is a closed local port: the client fails closed, fast (AC-003, NFR-003)."""

import socket
import time

import pytest
from pydantic import SecretStr

from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

pytestmark = pytest.mark.integration

CONNECT_TIMEOUT_SECONDS: float = 2.0


def _closed_port() -> int:
    """A localhost port nothing listens on (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@pytest.fixture
def unreachable_settings() -> Neo4jConnectionSettings:
    return Neo4jConnectionSettings(
        uri=f"bolt://127.0.0.1:{_closed_port()}",
        user="neo4j",
        password=SecretStr("never-sent"),
        connect_timeout_seconds=CONNECT_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("scheme", ["bolt", "neo4j"])
async def test_beginning_a_transaction_on_a_closed_port_fails_closed_within_the_timeout(
    unreachable_settings: Neo4jConnectionSettings, scheme: str
) -> None:
    settings = unreachable_settings.model_copy(
        update={"uri": unreachable_settings.uri.replace("bolt", scheme, 1)}
    )
    started: float = time.monotonic()

    async with Neo4jClient(settings) as client:
        with pytest.raises(GraphStoreUnavailableError) as raised:
            await client.begin()

    assert time.monotonic() - started < CONNECT_TIMEOUT_SECONDS
    assert raised.value.metadata["phase"] == "connect"
    assert raised.value.metadata["uri"] == settings.public_uri
    assert "commit_outcome" not in raised.value.metadata
    assert "never-sent" not in str(raised.value)


async def test_opening_a_transaction_on_a_closed_port_fails_closed(
    unreachable_settings: Neo4jConnectionSettings,
) -> None:
    async with Neo4jClient(unreachable_settings) as client:
        with pytest.raises(GraphStoreUnavailableError):
            async with await client.begin() as transaction:
                await transaction.run("RETURN 1")
