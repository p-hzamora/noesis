"""Shared Neo4j client: connection settings and error translation without a server."""

import pytest
from neo4j.exceptions import IncompleteCommit, ServiceUnavailable
from pydantic import SecretStr, ValidationError

from noesis.exceptions import ExitCodeEnum, GraphStoreUnavailableError
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    Neo4jClient,
    Neo4jConnectionSettings,
    Neo4jPhaseEnum,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j.neo4j_error_translator import (
    translate_neo4j_error,
)

pytestmark = pytest.mark.unit


def _settings(uri: str = "bolt://127.0.0.1:7687") -> Neo4jConnectionSettings:
    return Neo4jConnectionSettings(uri=uri, user="neo4j", password=SecretStr("s3cret-pass"))


def test_defaults_are_the_community_database_and_a_short_timeout() -> None:
    settings: Neo4jConnectionSettings = _settings()

    assert settings.database == "neo4j"
    assert settings.connect_timeout_seconds == DEFAULT_CONNECT_TIMEOUT_SECONDS == 5.0


@pytest.mark.parametrize("uri", ["http://127.0.0.1:7474", "127.0.0.1:7687", "bolt://"])
def test_a_uri_that_is_not_bolt_or_neo4j_is_rejected(uri: str) -> None:
    with pytest.raises(ValidationError):
        _settings(uri)


def test_the_public_uri_drops_credentials() -> None:
    settings: Neo4jConnectionSettings = _settings("neo4j+s://admin:hunter22@db.example:7687")

    assert settings.public_uri == "neo4j+s://db.example:7687"


def test_the_password_never_shows_in_a_repr() -> None:
    settings: Neo4jConnectionSettings = _settings()

    assert "s3cret-pass" not in repr(settings)
    assert "s3cret-pass" not in repr(Neo4jClient(settings))


@pytest.mark.parametrize("phase", [Neo4jPhaseEnum.CONNECT, Neo4jPhaseEnum.QUERY])
def test_a_lost_connection_is_the_unavailable_error_with_its_phase(phase: Neo4jPhaseEnum) -> None:
    error = translate_neo4j_error(
        ServiceUnavailable("Connection refused"), settings=_settings(), phase=phase
    )

    assert isinstance(error, GraphStoreUnavailableError)
    assert error.error_code == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert error.exit_code is ExitCodeEnum.FAILURE
    assert error.metadata == {
        "uri": "bolt://127.0.0.1:7687",
        "database": "neo4j",
        "connect_timeout_seconds": 5.0,
        "phase": phase.value,
    }
    assert any("idempotency key" in step for step in error.next_steps)


def test_a_connection_lost_during_commit_reports_an_unknown_outcome() -> None:
    error = translate_neo4j_error(
        IncompleteCommit("lost"), settings=_settings(), phase=Neo4jPhaseEnum.COMMIT
    )

    assert isinstance(error, GraphStoreUnavailableError)
    assert error.metadata["phase"] == "commit"
    assert error.metadata["commit_outcome"] == "unknown"


async def test_closing_a_client_that_never_connected_is_a_no_op() -> None:
    client = Neo4jClient(_settings())

    await client.close()
    await client.close()
