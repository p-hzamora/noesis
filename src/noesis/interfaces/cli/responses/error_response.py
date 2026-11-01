"""Failure envelope."""

from typing import Literal

from noesis.shared_kernel.domain import JsonObject
from noesis.utils import FrozenObject


class ErrorDetail(FrozenObject):
    """Body of a failed command's envelope.

    Attributes:
        code: Stable machine-readable error code.
        title: Short human title of the error class.
        message: What went wrong.
        metadata: Structured context for the error.
        next_steps: Commands or actions that can fix it.
    """

    code: str
    title: str
    message: str
    metadata: JsonObject
    next_steps: list[str]


class ErrorResponse(FrozenObject):
    """Envelope printed when a command fails and `--json` was asked for.

    Attributes:
        ok: Always `False`.
        error: What failed and what to do next.
    """

    ok: Literal[False] = False
    error: ErrorDetail
