"""Identity of an agent session."""

import re

from pydantic import field_validator

from noesis.exceptions import (
    InvalidSessionIdError,
)
from noesis.shared_kernel.domain.value_objects import ValueObject

SESSION_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SHORT_LENGTH: int = 8


class SessionId(ValueObject):
    """Letters, digits, `_` and `-` (Claude Code session ids are UUIDs).

    Attributes:
        value: The id.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _safe(cls, value: str) -> str:
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise InvalidSessionIdError(
                f"Invalid session id {value!r}.",
                {"session_id": value},
                next_steps=["Pass the agent's session id, e.g. --session ${CLAUDE_SESSION_ID}."],
            )
        return value

    @property
    def short(self) -> str:
        """First characters, for note frontmatter and logs."""
        return self.value[:SHORT_LENGTH]
