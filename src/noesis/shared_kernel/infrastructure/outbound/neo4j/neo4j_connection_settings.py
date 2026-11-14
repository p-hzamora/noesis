"""Where and how to reach one Neo4j database: the shared client's only input."""

from typing import Final
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, SecretStr, field_validator

from noesis.utils import FrozenObject

DEFAULT_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_DATABASE: Final[str] = "neo4j"
SUPPORTED_SCHEMES: Final[frozenset[str]] = frozenset(
    {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
)


class Neo4jConnectionSettings(FrozenObject):
    """Connection values for the shared Neo4j client.

    The composition root builds it from the user's settings (or a test from its container);
    the client never reads the environment itself.

    Attributes:
        uri: Bolt or routing URI, e.g. `bolt://127.0.0.1:7687`.
        user: Database user.
        password: Database password; a secret, masked in every repr and never in an error.
        database: Database name (Community has one user database, `neo4j`).
        connect_timeout_seconds: Upper bound to open a connection and to wait for one; a
            stopped store is reported within this time (NFR-003). Short by default.
    """

    uri: str
    user: str = Field(min_length=1)
    password: SecretStr
    database: str = Field(default=DEFAULT_DATABASE, min_length=1)
    connect_timeout_seconds: float = Field(default=DEFAULT_CONNECT_TIMEOUT_SECONDS, gt=0)

    @field_validator("uri", mode="after")
    @classmethod
    def _uri_has_a_supported_scheme_and_a_host(cls, uri: str) -> str:
        parts: SplitResult = urlsplit(uri)
        if parts.scheme not in SUPPORTED_SCHEMES or not parts.hostname:
            raise ValueError(
                f"expected a Neo4j URI such as bolt://127.0.0.1:7687 "
                f"(schemes: {', '.join(sorted(SUPPORTED_SCHEMES))})"
            )
        return uri

    @property
    def public_uri(self) -> str:
        """The URI without any user or password, safe for errors and logs."""
        parts: SplitResult = urlsplit(self.uri)
        host: str = parts.hostname or ""
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        netloc: str = f"{host}:{parts.port}" if parts.port is not None else host
        return parts._replace(netloc=netloc).geturl()
