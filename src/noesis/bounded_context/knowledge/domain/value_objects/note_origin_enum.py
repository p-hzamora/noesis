"""Who wrote a note."""

from enum import StrEnum


class NoteOriginEnum(StrEnum):
    """MANUAL: a person asked for it. AUTO: noesis wrote it with no person in the loop."""

    MANUAL = "manual"
    AUTO = "auto"
