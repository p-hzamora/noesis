"""The stderr notice of a command that is being replaced (Stage D of the retirement)."""

import os
import sys
from typing import Final

SILENCE_VARIABLE: Final[str] = "NOESIS_SILENCE_DEPRECATION"


def warn_deprecated(replacement: str) -> None:
    """Write `DEPRECATED: use <replacement>` to stderr unless `NOESIS_SILENCE_DEPRECATION=1`.

    Only stderr is touched; stdout stays exactly what the command printed before.
    """
    if os.environ.get(SILENCE_VARIABLE) == "1":
        return
    sys.stderr.write(f"DEPRECATED: use {replacement}\n")
