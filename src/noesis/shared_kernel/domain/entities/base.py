"""Base class for every domain entity."""

import abc
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    """Current UTC time; the default for entity timestamps."""
    return datetime.now(UTC)


@dataclass(slots=True, kw_only=True)
class Entity[T]:
    """Abstract base for domain entities: identity is defined by subclasses, timestamps here.

    Attributes:
        created_at: When the entity was first created.
        updated_at: When the entity last changed.
    """

    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    @abc.abstractmethod
    def create(cls, *args: Any, **kwargs: Any) -> T:
        """Build a new, valid entity."""
        ...

    def touch(self) -> None:
        """Record that the entity changed now."""
        self.updated_at = _now()
