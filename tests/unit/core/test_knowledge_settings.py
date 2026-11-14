"""Knowledge settings: defaults, validation, and the secret password."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from noesis.core import env_example_text, load_environment
from noesis.core.env import Environment, KnowledgeSettings
from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = pytest.mark.unit


def test_defaults_apply_without_file_or_variables() -> None:
    settings: KnowledgeSettings = load_environment().knowledge

    assert settings.neo4j_uri == "bolt://127.0.0.1:7687"
    assert settings.neo4j_user == "neo4j"
    assert settings.neo4j_database == "neo4j"
    assert settings.neo4j_connect_timeout_seconds == 5.0
    assert settings.knowledge_space == "personal"
    assert settings.neo4j_password is None


def test_values_come_from_the_file_and_the_password_is_masked(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(
        "NOESIS_NEO4J_URI=neo4j://db.example:7687\nNOESIS_NEO4J_PASSWORD=s3cret-value\n"
        "NOESIS_KNOWLEDGE_SPACE=team.alpha\nNOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS=2.5\n",
        encoding="utf-8",
    )

    environment: Environment = load_environment(env_file)
    settings: KnowledgeSettings = environment.knowledge

    assert settings.knowledge_space == "team.alpha"
    assert settings.neo4j_connect_timeout_seconds == 2.5
    assert isinstance(settings.neo4j_password, SecretStr)
    assert "s3cret-value" not in repr(settings)
    assert "s3cret-value" not in str(settings.model_dump(mode="json"))


def test_connection_carries_the_values_for_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_NEO4J_PASSWORD", "pw")
    monkeypatch.setenv("NOESIS_NEO4J_DATABASE", "other")

    connection: Neo4jConnectionSettings = load_environment().knowledge.neo4j_connection()

    assert connection.password.get_secret_value() == "pw"
    assert (connection.uri, connection.user, connection.database) == (
        "bolt://127.0.0.1:7687",
        "neo4j",
        "other",
    )


def test_connection_without_a_password_names_the_variable() -> None:
    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment().knowledge.neo4j_connection()

    assert raised.value.next_steps
    assert "NOESIS_NEO4J_PASSWORD" in str(raised.value)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("NOESIS_NEO4J_URI", "http://localhost:7474"),
        ("NOESIS_NEO4J_URI", "not a uri"),
        ("NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS", "0"),
        ("NOESIS_NEO4J_USER", ""),
        ("NOESIS_KNOWLEDGE_SPACE", "has space"),
        ("NOESIS_KNOWLEDGE_SPACE", ""),
    ],
)
def test_invalid_values_are_reported_by_variable_name(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment()

    assert variable in str(raised.value.metadata["problems"])


def test_the_template_documents_every_variable() -> None:
    template: str = env_example_text()

    for variable in (
        "NOESIS_NEO4J_URI",
        "NOESIS_NEO4J_USER",
        "NOESIS_NEO4J_PASSWORD",
        "NOESIS_NEO4J_DATABASE",
        "NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS",
        "NOESIS_KNOWLEDGE_SPACE",
    ):
        assert variable in template
