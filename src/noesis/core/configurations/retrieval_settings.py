"""Settings for search and the index commands."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings

DEFAULT_INDEX_LOCK_TTL_SECONDS: int = 300


class RetrievalSettings(AppBaseSettings):
    """How long an index lock lives.

    Attributes:
        index_lock_ttl_seconds: Seconds a sync or rebuild may hold a projection's lock before
            another process may take it over (`NOESIS_INDEX_LOCK_TTL_SECONDS`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    index_lock_ttl_seconds: int = Field(default=DEFAULT_INDEX_LOCK_TTL_SECONDS, gt=0)
