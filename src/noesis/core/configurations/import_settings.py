"""Settings of the vault import: the vault folder and the key its locators carry."""

import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from noesis.exceptions import InvalidConfigurationError

from .base_settings import AppBaseSettings

VAULT_KEY_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")
VAULT_KEY_VARIABLE: str = "NOESIS_IMPORT_VAULT_KEY"


class ImportSettings(AppBaseSettings):
    """Where `noesis import run` reads from, and the key of the locators it records.

    Construction accepts any key: every settings class is built when the CLI starts, so a bad
    key must not break an unrelated command. `resolve_vault_key` validates it when an import
    command starts.

    Attributes:
        vault_dir: Vault folder, read only by `import run` (`NOESIS_VAULT_DIR`). None until set.
        import_vault_key: Key in `vault://<key>/<relative path>` locators
            (`NOESIS_IMPORT_VAULT_KEY`); letters, digits, `.`, `_`, `-`. None means the vault
            folder's name.
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_")

    vault_dir: Path | None = None
    import_vault_key: str | None = None

    @field_validator("vault_dir", mode="after")
    @classmethod
    def _expand_vault_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    def resolve_vault_key(self) -> str:
        """The key to use in locators: the given one, else the vault folder's name.

        Raises:
            InvalidConfigurationError: The key, given or derived, is not letters, digits, `.`,
                `_` and `-`, or neither a key nor a vault folder is set.
        """
        key: str | None = self.import_vault_key
        if key is None and self.vault_dir is not None:
            key = self.vault_dir.name
        if key is None or not VAULT_KEY_PATTERN.fullmatch(key):
            raise InvalidConfigurationError(
                f"{VAULT_KEY_VARIABLE} is not a valid vault key: {key!r}.",
                {"variable": VAULT_KEY_VARIABLE, "value": key},
                next_steps=[
                    f"Set {VAULT_KEY_VARIABLE} to letters, digits, '.', '_' or '-' "
                    "(the default is the vault folder name)."
                ],
            )
        return key
