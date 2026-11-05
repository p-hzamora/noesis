"""File-name-safe identifier of a note inside its folder."""

import re
from typing import Self

from pydantic import field_validator

from noesis.exceptions import (
    InvalidNoteSlugError,
)
from noesis.shared_kernel.domain.value_objects import ValueObject

SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SLUG_LENGTH: int = 80


class NoteSlug(ValueObject):
    """Lowercase letters, digits and single hyphens, at most 80 characters.

    Attributes:
        value: The slug.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if len(value) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(value):
            raise InvalidNoteSlugError(
                f"Invalid note slug {value!r}.",
                {"slug": value},
                next_steps=["Use lowercase letters, digits and single hyphens (max 80)."],
            )
        return value

    @classmethod
    def from_title(cls, title: str) -> Self:
        """Derive a slug from a free-text title (`Use TTL cache!` -> `use-ttl-cache`)."""
        words: list[str] = re.findall(r"[a-z0-9]+", title.lower())
        return cls(value="-".join(words)[:MAX_SLUG_LENGTH].strip("-") or "note")
