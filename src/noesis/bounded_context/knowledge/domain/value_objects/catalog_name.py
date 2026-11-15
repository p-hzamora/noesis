"""The name of a catalog entry: stored as typed, compared case-sensitively."""

import re
from typing import Final

from pydantic import field_validator

from noesis.exceptions import InvalidCatalogNameError
from noesis.shared_kernel.domain.value_objects import ValueObject

CATALOG_NAME_PATTERN: Final[str] = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_NAME: Final[re.Pattern[str]] = re.compile(CATALOG_NAME_PATTERN)


class CatalogEntryName(ValueObject):
    """A skill, agent, CLI tool or MCP server name, optionally qualified as `<plugin>:<name>`.

    Attributes:
        value: 1 to 128 ASCII letters, digits, `.`, `_`, `-` or `:`, starting with a letter or
            digit. Never normalised: `Gh` and `gh` are two names.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _grammar(cls, value: str) -> str:
        if _NAME.fullmatch(value) is None:
            raise InvalidCatalogNameError(
                f"Invalid catalog name {value!r}.",
                {"name": value},
                next_steps=[
                    "Use 1 to 128 ASCII letters, digits, '.', '_', '-' or ':', "
                    "starting with a letter or digit."
                ],
            )
        return value
