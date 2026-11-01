"""Base class for domain value objects: immutable and equal by value."""

from noesis.utils import FrozenObject


class ValueObject(FrozenObject):
    """Immutable domain value; a single-field value object prints as its `value`."""

    def __str__(self) -> str:
        value: object = getattr(self, "value", None)
        return str(value) if value is not None else super().__str__()
