"""`IClock` backed by the operating system clock."""

from datetime import UTC, datetime

from noesis.shared_kernel.application.ports.clock import IClock


class SystemClockAdapter(IClock):
    """Wall-clock time in UTC."""

    def now(self) -> datetime:
        """The current UTC time."""
        return datetime.now(UTC)
