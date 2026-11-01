"""Base class for application DTOs: what handlers return across the application boundary."""

from noesis.utils import FrozenObject


class BaseDto(FrozenObject):
    """Immutable output contract of a command or query handler."""
