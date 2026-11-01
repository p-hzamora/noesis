"""Process exit codes: the CLI's equivalent of HTTP status codes."""

from enum import IntEnum


class ExitCodeEnum(IntEnum):
    """What a finished command tells its caller (a shell, a script, an agent)."""

    OK = 0
    FAILURE = 1
    USAGE = 2
