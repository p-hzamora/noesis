"""Fault injection: the store goes away between two commands and the same key is retried.

Uses a DEDICATED container on a fixed host port (so it can be stopped and restarted without
touching the shared session container).
"""

import secrets
import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from neo4j import GraphDatabase
from pydantic import SecretStr
from testcontainers.community.neo4j import Neo4jContainer
from tests.support.neo4j_container import (
    NEO4J_USER,
    admin_driver,
    docker_unavailable_reason,
    pinned_neo4j_image,
)
from tests.support.noesis_process_support import capture_command, run_noesis, store_environment

from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_serving(settings: Neo4jConnectionSettings, seconds: float = 90.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with GraphDatabase.driver(
                settings.uri, auth=(settings.user, settings.password.get_secret_value())
            ) as driver:
                driver.verify_connectivity()
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


@pytest.fixture
def restartable() -> Iterator[tuple[Neo4jContainer, Neo4jConnectionSettings]]:
    if reason := docker_unavailable_reason():
        pytest.skip(reason)
    password = secrets.token_urlsafe(16)
    port = _free_port()
    container = Neo4jContainer(pinned_neo4j_image(), username=NEO4J_USER, password=password)
    container.with_bind_ports(7687, port)
    settings = Neo4jConnectionSettings(
        uri=f"bolt://127.0.0.1:{port}",
        user=NEO4J_USER,
        password=SecretStr(password),
        connect_timeout_seconds=2,
    )
    with container:
        yield container, settings


def test_a_retry_with_the_same_key_after_an_outage_stores_exactly_one_record(
    restartable: tuple[Neo4jContainer, Neo4jConnectionSettings], tmp_path: Path
) -> None:
    container, settings = restartable
    env = {
        **store_environment(tmp_path / "home", "outage", settings),
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS": "2",
    }
    assert run_noesis(["store", "init"], env).code == 0
    wrapped = container.get_wrapped_container()
    assert wrapped is not None

    wrapped.stop(timeout=5)
    down = run_noesis(capture_command("outage-key"), env)
    wrapped.start()
    _wait_until_serving(settings)
    retried = run_noesis(capture_command("outage-key"), env)
    again = run_noesis(capture_command("outage-key"), env)

    assert down.code == 1
    assert down.error["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"
    assert down.error["next_steps"]
    assert retried.code == 0 and again.code == 0
    assert again.result["record_id"] == retried.result["record_id"]
    assert again.result["replayed"] is True
    with admin_driver(settings) as driver:
        rows, _, _ = driver.execute_query(
            "MATCH (r:Knowledge) RETURN count(r) AS c", database_=settings.database
        )
    assert rows[0]["c"] == 1
