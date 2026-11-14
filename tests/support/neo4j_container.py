"""The pinned Neo4j test container (D-016, D-022): start it, reach it, wipe it.

The image tag is read from the repository's `compose.yaml`, so tests and local use run the
same Neo4j. Connection values come from the container only; nothing here reads the user's
`NOESIS_NEO4J_*` settings or profile files (NFR-004).
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import yaml
from neo4j import Driver, GraphDatabase
from pydantic import SecretStr
from testcontainers.community.neo4j import Neo4jContainer
from testcontainers.core.docker_client import DockerClient

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

COMPOSE_FILE: Final[Path] = Path(__file__).resolve().parents[2] / "compose.yaml"
NEO4J_USER: Final[str] = "neo4j"
TEST_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0


def pinned_neo4j_image() -> str:
    """The exact Neo4j image tag `compose.yaml` pins (the single place it is written)."""
    compose: dict[str, dict[str, dict[str, str]]] = yaml.safe_load(
        COMPOSE_FILE.read_text(encoding="utf-8")
    )
    return compose["services"]["neo4j"]["image"]


def docker_unavailable_reason() -> str | None:
    """Why no container can start here, or `None` when a Docker daemon answers."""
    try:
        DockerClient().client.ping()
    except Exception as error:  # any failure to reach Docker means "skip"
        return f"Docker is not available ({type(error).__name__}); neo4j tests need it"
    return None


@contextmanager
def running_neo4j() -> Iterator[Neo4jConnectionSettings]:
    """Start the pinned image with a random password and yield how to reach it.

    Yields:
        Connection settings for the container's Bolt port on this host.
    """
    password: str = secrets.token_urlsafe(16)
    with Neo4jContainer(pinned_neo4j_image(), username=NEO4J_USER, password=password) as container:
        yield Neo4jConnectionSettings(
            uri=container.get_connection_url(),
            user=NEO4J_USER,
            password=SecretStr(password),
            connect_timeout_seconds=TEST_CONNECT_TIMEOUT_SECONDS,
        )


@contextmanager
def admin_driver(settings: Neo4jConnectionSettings) -> Iterator[Driver]:
    """A synchronous driver for test setup and inspection, closed on exit."""
    driver: Driver = GraphDatabase.driver(
        settings.uri, auth=(settings.user, settings.password.get_secret_value())
    )
    try:
        yield driver
    finally:
        driver.close()


def wipe_database(settings: Neo4jConnectionSettings) -> None:
    """Delete every node, constraint and (non-lookup) index, so each test starts empty."""
    with admin_driver(settings) as driver:
        driver.execute_query("MATCH (n) DETACH DELETE n", database_=settings.database)
        constraints, _, _ = driver.execute_query(
            "SHOW CONSTRAINTS YIELD name RETURN name", database_=settings.database
        )
        for row in constraints:
            driver.execute_query(f"DROP CONSTRAINT `{row['name']}`", database_=settings.database)
        indexes, _, _ = driver.execute_query(
            "SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name",
            database_=settings.database,
        )
        for row in indexes:
            driver.execute_query(f"DROP INDEX `{row['name']}`", database_=settings.database)
