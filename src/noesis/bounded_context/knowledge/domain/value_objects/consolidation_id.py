"""Identity of a consolidation."""

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.ulid import ULID_PATTERN
from noesis.exceptions import InvalidRecordIdError
from noesis.shared_kernel.domain.value_objects import ValueObject


class ConsolidationId(ValueObject):
    """A ULID naming one consolidation; a consolidation is bookkeeping, never a record.

    Attributes:
        value: The ULID.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not ULID_PATTERN.fullmatch(value):
            raise InvalidRecordIdError(
                f"Invalid consolidation id {value!r}.",
                {"id": value},
                next_steps=["A consolidation id is a 26-character uppercase ULID."],
            )
        return value
