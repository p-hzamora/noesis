"""What a migration plan does with one file."""

from enum import StrEnum


class MigrationActionEnum(StrEnum):
    """`note` adds or refreshes frontmatter and moves; `move` relocates bytes; `keep` leaves it."""

    NOTE = "note"
    MOVE = "move"
    KEEP = "keep"
