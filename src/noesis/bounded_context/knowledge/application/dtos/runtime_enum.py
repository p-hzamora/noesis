"""An agent runtime whose installed capabilities can be listed."""

from enum import StrEnum


class RuntimeEnum(StrEnum):
    """An agent runtime whose installed capabilities can be listed."""

    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
