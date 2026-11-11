"""Stable identity of a note, independent of where its file lives."""

import re

from pydantic import field_validator

from noesis.exceptions import InvalidNoteIdError
from noesis.shared_kernel.domain.value_objects import ValueObject

ULID_PATTERN: re.Pattern[str] = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


class NoteId(ValueObject):
    """A ULID: 26 Crockford base32 characters, sortable by creation time.

    The id lives in the note's frontmatter, so moving or renaming the file never changes it.

    Attributes:
        value: The ULID.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not ULID_PATTERN.fullmatch(value):
            raise InvalidNoteIdError(
                f"Invalid note id {value!r}.",
                {"id": value},
                next_steps=["A note id is a 26-character uppercase ULID."],
            )
        return value
