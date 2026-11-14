"""Digest of a file version, as `sha256:<hex>`."""

import hashlib
import re

from pydantic import field_validator

from noesis.exceptions import InvalidContentHashError
from noesis.shared_kernel.domain.value_objects import ValueObject

HASH_PATTERN: re.Pattern[str] = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContentHash(ValueObject):
    """`sha256:` followed by 64 lowercase hex digits.

    Attributes:
        value: The hash string.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not HASH_PATTERN.fullmatch(value):
            raise InvalidContentHashError(
                f"Invalid content hash {value!r}.",
                {"hash": value},
                next_steps=["A content hash is `sha256:` followed by 64 lowercase hex digits."],
            )
        return value

    @classmethod
    def of(cls, data: bytes) -> ContentHash:
        """The hash of `data`."""
        return cls(value=f"sha256:{hashlib.sha256(data).hexdigest()}")
