"""Identity of a knowledge space."""

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.ulid import ULID_PATTERN
from noesis.exceptions import InvalidRecordIdError
from noesis.shared_kernel.domain.value_objects import ValueObject


class SpaceId(ValueObject):
    """A ULID naming one knowledge space.

    Attributes:
        value: The ULID.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not ULID_PATTERN.fullmatch(value):
            raise InvalidRecordIdError(
                f"Invalid space id {value!r}.",
                {"id": value},
                next_steps=["A space id is a 26-character uppercase ULID."],
            )
        return value
