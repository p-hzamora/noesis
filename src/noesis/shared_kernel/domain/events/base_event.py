"""Immutable base for every domain event."""

import datetime as dt
from uuid import UUID, uuid4

from pydantic import Field

from noesis.shared_kernel.domain.types import JsonValue
from noesis.utils import FrozenObject


def _now() -> dt.datetime:
    """Current UTC time; the default for `occurred_at`."""
    return dt.datetime.now(dt.UTC)


class DomainEvent[T](FrozenObject):
    """Something that happened inside an aggregate.

    Attributes:
        event_id: Unique id of this occurrence.
        aggregate_id: Id of the aggregate that recorded the event.
        occurred_at: When it happened (UTC).
        payload: Event data, JSON-compatible.
    """

    event_id: UUID = Field(default_factory=uuid4)
    aggregate_id: str
    occurred_at: dt.datetime = Field(default_factory=_now)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
