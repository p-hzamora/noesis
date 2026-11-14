"""Settings for the knowledge store: the Neo4j connection and the active knowledge space."""

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import SettingsConfigDict

from noesis.bounded_context.knowledge.domain.value_objects.key import KEY_PATTERN
from noesis.exceptions import InvalidConfigurationError
from noesis.shared_kernel.infrastructure.outbound.neo4j import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_DATABASE,
    Neo4jConnectionSettings,
)

from .base_settings import AppBaseSettings

DEFAULT_NEO4J_URI: str = "bolt://127.0.0.1:7687"
DEFAULT_NEO4J_USER: str = "neo4j"
DEFAULT_KNOWLEDGE_SPACE: str = "personal"


class KnowledgeSettings(AppBaseSettings):
    """Where the record store lives and which space commands act in.

    Attributes:
        neo4j_uri: Bolt or routing URI (`NOESIS_NEO4J_URI`).
        neo4j_user: Database user (`NOESIS_NEO4J_USER`).
        neo4j_password: Database password, a secret (`NOESIS_NEO4J_PASSWORD`). Read it only from
            a user-side profile or the environment (ADR-0001 Amendment 3); it is masked in
            `repr` and `config show`. None until the user sets it.
        neo4j_database: Database name; Community has one user database (`NOESIS_NEO4J_DATABASE`).
        neo4j_connect_timeout_seconds: Time limit to reach the store; an unreachable store fails
            closed within it (`NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS`).
        knowledge_space: Key of the space commands act in; `store init` ensures it exists
            (`NOESIS_KNOWLEDGE_SPACE`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    neo4j_uri: str = DEFAULT_NEO4J_URI
    neo4j_user: str = Field(default=DEFAULT_NEO4J_USER, min_length=1)
    neo4j_password: SecretStr | None = None
    neo4j_database: str = Field(default=DEFAULT_DATABASE, min_length=1)
    neo4j_connect_timeout_seconds: float = Field(default=DEFAULT_CONNECT_TIMEOUT_SECONDS, gt=0)
    knowledge_space: str = Field(default=DEFAULT_KNOWLEDGE_SPACE, pattern=KEY_PATTERN.pattern)

    @field_validator("neo4j_uri", mode="after")
    @classmethod
    def _uri_is_a_neo4j_uri(cls, uri: str) -> str:
        # one rule for the URI: the client's own settings class
        try:
            Neo4jConnectionSettings(uri=uri, user=DEFAULT_NEO4J_USER, password=SecretStr("-"))
        except ValidationError as error:
            raise ValueError(error.errors()[0]["msg"]) from None
        return uri

    def neo4j_connection(self) -> Neo4jConnectionSettings:
        """The connection values for the shared Neo4j client.

        Raises:
            InvalidConfigurationError: `NOESIS_NEO4J_PASSWORD` is not set.
        """
        if self.neo4j_password is None:
            raise InvalidConfigurationError(
                "NOESIS_NEO4J_PASSWORD is not set.",
                {"variable": "NOESIS_NEO4J_PASSWORD"},
                next_steps=[
                    "Set NOESIS_NEO4J_PASSWORD in your user-side profile "
                    "(~/.config/noesis/.env) or the environment."
                ],
            )
        return Neo4jConnectionSettings(
            uri=self.neo4j_uri,
            user=self.neo4j_user,
            password=self.neo4j_password,
            database=self.neo4j_database,
            connect_timeout_seconds=self.neo4j_connect_timeout_seconds,
        )
