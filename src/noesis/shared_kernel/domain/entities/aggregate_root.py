"""Base class for aggregate roots, which collect domain events until they are published."""

from dataclasses import dataclass, field
from typing import Any

from noesis.shared_kernel.domain.entities.base import Entity
from noesis.shared_kernel.domain.events import (
    DomainEvent,
)


@dataclass(slots=True, kw_only=True)
class AggregateRoot[T](Entity[T]):
    """Consistency boundary that records what happened as pending domain events.

    Attributes:
        pending_events: Events recorded since the last `collect_events` call.
    """

    pending_events: list[DomainEvent[Any]] = field(default_factory=list)

    def _record(self, event: DomainEvent[Any]) -> None:
        """Append a domain event to the pending list."""
        self.pending_events.append(event)

    def collect_events(self) -> list[DomainEvent[Any]]:
        """Return the pending events and clear the buffer."""
        events: list[DomainEvent[Any]] = list(self.pending_events)
        self.pending_events.clear()
        return events
