"""Identity of a record: unique across every record type."""

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.ulid import ULID_PATTERN
from noesis.exceptions import InvalidRecordIdError
from noesis.shared_kernel.domain.value_objects import ValueObject


class RecordId(ValueObject):
    """A ULID. Existing frontmatter ULIDs are accepted as they are.

    Attributes:
        value: The ULID (26 uppercase Crockford base32 characters).
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not ULID_PATTERN.fullmatch(value):
            raise InvalidRecordIdError(
                f"Invalid record id {value!r}.",
                {"id": value},
                next_steps=["A record id is a 26-character uppercase ULID."],
            )
        return value
