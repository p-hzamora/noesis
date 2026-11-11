"""`INoteIdGenerator` that makes ULIDs: 48-bit millisecond timestamp, then 80 random bits."""

import secrets

from noesis.bounded_context.notes.application.ports.ids import INoteIdGenerator
from noesis.bounded_context.notes.domain.value_objects import NoteId
from noesis.shared_kernel.application.ports.clock import IClock

CROCKFORD: str = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TIMESTAMP_CHARS: int = 10
RANDOM_BITS: int = 80
ID_LENGTH: int = 26


def _encode(number: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(CROCKFORD[number & 31])
        number >>= 5
    return "".join(reversed(chars))


class UlidNoteIdGeneratorAdapter(INoteIdGenerator):
    """Ids sort by creation time; two notes created in the same millisecond still differ."""

    def __init__(self, clock: IClock) -> None:
        self._clock: IClock = clock

    def new_id(self) -> NoteId:
        """A new ULID stamped with the clock's time."""
        millis: int = int(self._clock.now().timestamp() * 1000)
        randomness: int = secrets.randbits(RANDOM_BITS)
        return NoteId(
            value=_encode(millis, TIMESTAMP_CHARS)
            + _encode(randomness, ID_LENGTH - TIMESTAMP_CHARS)
        )
