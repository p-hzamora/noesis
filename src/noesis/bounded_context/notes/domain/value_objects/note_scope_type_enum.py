"""What kind of thing a scope names."""

from enum import StrEnum


class NoteScopeTypeEnum(StrEnum):
    """REPO: the notes of one repository. TOPIC: the notes of one learning topic."""

    REPO = "repo"
    TOPIC = "topic"
