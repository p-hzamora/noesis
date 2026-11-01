"""Clock port, so time-dependent rules (debounce, timestamps) are testable."""

import abc
from datetime import datetime


class IClock(abc.ABC):
    """Source of the current time."""

    @abc.abstractmethod
    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""
        ...
