"""What a note records, by name; which names exist is the manifest's decision."""

import re

from pydantic import field_validator

from noesis.exceptions import InvalidNoteKindError
from noesis.shared_kernel.domain.value_objects import ValueObject

KIND_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_KIND_LENGTH: int = 40


class NoteKind(ValueObject):
    """A kind name of valid shape. Membership in the kind catalog is checked by the application.

    Attributes:
        value: Lowercase words joined by single hyphens.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if len(value) > MAX_KIND_LENGTH or not KIND_PATTERN.fullmatch(value):
            raise InvalidNoteKindError(
                f"Invalid note kind {value!r}.",
                {"kind": value},
                next_steps=["Use lowercase words joined by hyphens, starting with a letter."],
            )
        return value
