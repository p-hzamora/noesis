"""Entity, aggregate root, value object and domain event bases."""

from dataclasses import dataclass
from typing import Self

import pytest
from pydantic import ValidationError

from noesis.shared_kernel.domain.entities import AggregateRoot
from noesis.shared_kernel.domain.events import DomainEvent
from noesis.shared_kernel.domain.value_objects import ValueObject

pytestmark = pytest.mark.unit


class _Name(ValueObject):
    value: str


class _Renamed(DomainEvent["_Thing"]):
    pass


@dataclass(slots=True, kw_only=True)
class _Thing(AggregateRoot["_Thing"]):
    name: _Name

    @classmethod
    def create(cls, name: str) -> Self:
        return cls(name=_Name(value=name))

    def rename(self, name: str) -> None:
        self.name = _Name(value=name)
        self.touch()
        self._record(_Renamed(aggregate_id=name, payload={"name": name}))


def test_value_objects_are_equal_by_value_immutable_and_print_their_value() -> None:
    name: _Name = _Name(value="noesis")

    assert name == _Name(value="noesis")
    assert str(name) == "noesis"
    with pytest.raises(ValidationError):
        name.value = "other"  # type: ignore[misc]


def test_aggregate_collects_recorded_events_once_and_touches_updated_at() -> None:
    thing: _Thing = _Thing.create("old")
    created: object = thing.updated_at

    thing.rename("new")

    events = thing.collect_events()
    assert [event.payload for event in events] == [{"name": "new"}]
    assert thing.collect_events() == []
    assert thing.updated_at >= created  # type: ignore[operator]
