"""The single owner of the settings-loading policy shared by every settings class."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppBaseSettings(BaseSettings):
    """Shared policy: UTF-8 `.env` files, unknown keys ignored, inputs hidden in errors, immutable.

    The `.env` path is not fixed here: `noesis.core.env.load_environment` passes it at
    construction time, so tests and `--env-file` can point elsewhere.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
        validate_default=True,
    )
