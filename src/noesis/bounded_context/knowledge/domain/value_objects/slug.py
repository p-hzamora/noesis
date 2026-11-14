"""Validated slug: the open vocabulary of knowledge subtypes."""

import re

from pydantic import field_validator

from noesis.exceptions import InvalidSlugError
from noesis.shared_kernel.domain.value_objects import ValueObject

SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SLUG_LENGTH: int = 64


def check_slug(value: str) -> str:
    """`value` when it is a valid slug.

    Raises:
        InvalidSlugError: The value is empty, too long, or not lowercase words joined by hyphens.
    """
    if len(value) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(value):
        raise InvalidSlugError(
            f"Invalid slug {value!r}.",
            {"slug": value},
            next_steps=[
                f"Use lowercase letters, digits and single hyphens, up to {MAX_SLUG_LENGTH} characters."
            ],
        )
    return value


class Slug(ValueObject):
    """Lowercase letters and digits joined by single hyphens.

    Attributes:
        value: The slug.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        return check_slug(value)
