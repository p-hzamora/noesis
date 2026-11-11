"""A pointer to what a note's knowledge came from."""

import re

from pydantic import field_validator

from noesis.exceptions import InvalidNoteSourceRefError
from noesis.shared_kernel.domain.value_objects import ValueObject

SOURCE_REF_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_-]*:\S+$")


class NoteSourceRef(ValueObject):
    """`<type>:<id>`, for example `commit:8e6d3b5f` or `session:abcd1234`.

    Attributes:
        value: The reference.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not SOURCE_REF_PATTERN.fullmatch(value):
            raise InvalidNoteSourceRefError(
                f"Invalid note source reference {value!r}.",
                {"source": value},
                next_steps=["Use `<type>:<id>`, e.g. `commit:<sha>` or `session:<id>`."],
            )
        return value
