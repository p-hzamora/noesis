"""`IRecordIdGenerator` that makes ULIDs: 48-bit millisecond timestamp, then 80 random bits."""

import secrets
from typing import Final

from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.shared_kernel.application.ports.clock import IClock

CROCKFORD: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TIMESTAMP_CHARS: Final[int] = 10
RANDOM_BITS: Final[int] = 80
ID_LENGTH: Final[int] = 26


def _encode(number: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(CROCKFORD[number & 31])
        number >>= 5
    return "".join(reversed(chars))


class UlidRecordIdGeneratorAdapter(IRecordIdGenerator):
    """Ids sort by creation time; two ids made in the same millisecond still differ."""

    def __init__(self, clock: IClock) -> None:
        self._clock: IClock = clock

    def _new_ulid(self) -> str:
        millis: int = int(self._clock.now().timestamp() * 1000)
        randomness: int = secrets.randbits(RANDOM_BITS)
        return _encode(millis, TIMESTAMP_CHARS) + _encode(randomness, ID_LENGTH - TIMESTAMP_CHARS)

    def new_record_id(self) -> RecordId:
        """A new ULID record id stamped with the clock's time."""
        return RecordId(value=self._new_ulid())

    def new_space_id(self) -> SpaceId:
        """A new ULID space id stamped with the clock's time."""
        return SpaceId(value=self._new_ulid())
