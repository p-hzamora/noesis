"""Human-chosen unique name of a space or a project."""

import re

from pydantic import field_validator

from noesis.exceptions import InvalidKeyError
from noesis.shared_kernel.domain.value_objects import ValueObject

KEY_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class Key(ValueObject):
    """A short name without spaces: a repository folder name or a configured space name.

    Attributes:
        value: The key, kept as written.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not KEY_PATTERN.fullmatch(value):
            raise InvalidKeyError(
                f"Invalid key {value!r}.",
                {"key": value},
                next_steps=[
                    "Use letters, digits, dots, hyphens and underscores, starting with a letter or digit."
                ],
            )
        return value
