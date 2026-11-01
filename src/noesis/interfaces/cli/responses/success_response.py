"""Success envelope."""

from typing import Literal

from noesis.utils import FrozenObject


class SuccessResponse[T: FrozenObject](FrozenObject):
    """Envelope printed on stdout when a command succeeds.

    Attributes:
        ok: Always `True`; lets machine readers branch without inspecting `result`.
        result: The command's response.
    """

    ok: Literal[True] = True
    result: T
